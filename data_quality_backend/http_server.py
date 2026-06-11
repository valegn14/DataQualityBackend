from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, time, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import uuid4

from .contracts import AgentRequest, ColumnMetadata, RelationMetadata, SchemaMetadata, TableMetadata
from .auth import ApiKeyAuthenticator, AuthError
from .default_components import ConsoleAuditLogger, DefaultResultFormatter, StaticQueryPlanner
from .mcp_client import InMemoryDatabaseSpec, LocalMCPServerClient, MCPServerClient
from .http_mcp_client import HTTPMCPServerClient
from .mcp_schema_inspector import MCPBackedSchemaInspector
from .orchestrator import DatabaseOrchestrator
from .planner import HeuristicQueryPlanner, OllamaQueryPlanner, QueryPlanner
from .schema_cache import SchemaCache
from .settings import AppSettings
from .validator import QueryValidator


class AgentHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_cls: type[BaseHTTPRequestHandler], orchestrator: DatabaseOrchestrator, settings: AppSettings) -> None:
        super().__init__(server_address, handler_cls)
        self.orchestrator = orchestrator
        self.settings = settings
        self.authenticator = ApiKeyAuthenticator(settings.http_api_key)


class AgentRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        self._send_json({"status": "ok", "service": "data-analysis-backend"}, HTTPStatus.OK)

    def do_POST(self) -> None:
        if self.path != "/query":
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            authenticator = self.server.authenticator  # type: ignore[attr-defined]
            auth_context = authenticator.authenticate({k: v for k, v in self.headers.items()})
            payload = self._read_json()
            request = self._build_request(payload)
            request.user_id = auth_context.principal_id
            if bool(payload.get("stream")):
                self._stream_query(request)
                return

            result = self.server.orchestrator.execute(request)  # type: ignore[attr-defined]
            self._send_json(
                {
                    "ok": result.validation.is_valid,
                    "data": {
                        "request_id": result.request_id,
                        "database_id": result.database_id,
                        "database_ids": result.database_ids,
                        "sql": result.sql,
                        "intent": result.intent,
                        "plan_steps": result.plan_steps,
                        "context": result.context,
                        "validation": {
                            "is_valid": result.validation.is_valid,
                            "reasons": result.validation.reasons,
                        },
                        "result": asdict(result.result) if result.result is not None else None,
                        "formatted_result": result.formatted_result,
                        "assistant_history": result.assistant_history,
                        "executed_queries": result.executed_queries,
                        "final_comment": result.final_comment,
                        "progress": result.progress,
                    },
                },
                HTTPStatus.OK,
            )
        except AuthError as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.UNAUTHORIZED)
        except (KeyError, TypeError, ValueError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # pragma: no cover - server boundary
            self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _stream_query(self, request: AgentRequest) -> None:
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def emit(message: str) -> None:
            self._write_sse_event("progress", {"message": message})

        self._write_sse_event("progress", {"message": "Solicitud recibida"})
        result = self.server.orchestrator.execute(request, progress_callback=emit)  # type: ignore[attr-defined]
        self._write_sse_event(
            "final",
            {
                "ok": result.validation.is_valid,
                "data": {
                    "request_id": result.request_id,
                    "database_id": result.database_id,
                    "database_ids": result.database_ids,
                    "sql": result.sql,
                    "intent": result.intent,
                    "plan_steps": result.plan_steps,
                    "context": result.context,
                    "validation": {
                        "is_valid": result.validation.is_valid,
                        "reasons": result.validation.reasons,
                    },
                    "result": asdict(result.result) if result.result is not None else None,
                    "formatted_result": result.formatted_result,
                    "assistant_history": result.assistant_history,
                    "executed_queries": result.executed_queries,
                    "final_comment": result.final_comment,
                    "progress": result.progress,
                },
            },
        )
        self.wfile.write(b"event: done\ndata: {}\n\n")
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        if not body:
            raise ValueError("Request body is required.")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _build_request(self, payload: dict[str, Any]) -> AgentRequest:
        prompt = payload.get("prompt")
        database_id = payload.get("database_id")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Field 'prompt' is required.")
        if not isinstance(database_id, str) or not database_id.strip():
            raise ValueError("Field 'database_id' is required.")

        settings = self.server.settings  # type: ignore[attr-defined]
        request_id = payload.get("request_id") if isinstance(payload.get("request_id"), str) else f"req-{uuid4().hex}"
        user_id = payload.get("user_id") if isinstance(payload.get("user_id"), str) else "http-user"
        allow_write = bool(payload.get("allow_write", settings.allow_write_default))
        max_rows = payload.get("max_rows") if isinstance(payload.get("max_rows"), int) else settings.default_max_rows
        max_attempts = payload.get("max_attempts") if isinstance(payload.get("max_attempts"), int) else None
        preferred_dialect = payload.get("preferred_dialect") if isinstance(payload.get("preferred_dialect"), str) else None
        assistant_context = payload.get("assistant_context") if isinstance(payload.get("assistant_context"), list) else []
        raw_database_ids = payload.get("database_ids") if isinstance(payload.get("database_ids"), list) else None
        database_ids = [str(item) for item in raw_database_ids if isinstance(item, str)] if raw_database_ids is not None else None

        return AgentRequest(
            request_id=request_id,
            user_id=user_id,
            prompt=prompt,
            database_id=database_id,
            database_ids=database_ids,
            allow_write=allow_write,
            max_rows=max_rows,
            max_attempts=max_attempts,
            preferred_dialect=preferred_dialect,
            assistant_context=assistant_context,
        )

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=self._json_default).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_sse_event(self, event: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=self._json_default)
        self.wfile.write(f"event: {event}\n".encode("utf-8"))
        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _json_default(self, value: object) -> object:
        if isinstance(value, (datetime, date, time)):
            return value.isoformat()
        return str(value)


def build_demo_schema(database_id: str, ttl_seconds: int) -> SchemaMetadata:
    return SchemaMetadata(
        database_id=database_id,
        schema_version="demo-v1",
        fetched_at=datetime.now(timezone.utc),
        ttl_seconds=ttl_seconds,
        dialect="postgresql",
        tables=[
            TableMetadata(
                name="customers",
                columns=[
                    ColumnMetadata(name="id", type="uuid", nullable=False, is_primary_key=True),
                    ColumnMetadata(name="name", type="text", nullable=False),
                    ColumnMetadata(name="email", type="text", nullable=False),
                ],
                primary_key=["id"],
                is_view=False,
            ),
            TableMetadata(
                name="orders",
                columns=[
                    ColumnMetadata(name="id", type="uuid", nullable=False, is_primary_key=True),
                    ColumnMetadata(name="customer_id", type="uuid", nullable=False, is_foreign_key=True),
                    ColumnMetadata(name="total", type="numeric", nullable=False),
                ],
                primary_key=["id"],
                is_view=False,
            ),
        ],
        relations=[RelationMetadata("customers", "id", "orders", "customer_id")],
    )


def build_demo_orchestrator(settings: AppSettings | None = None, query_planner: QueryPlanner | None = None) -> DatabaseOrchestrator:
    resolved_settings = settings or AppSettings.from_env()
    database_id = resolved_settings.demo_database_id
    schema_metadata = build_demo_schema(database_id, resolved_settings.schema_cache_ttl_seconds)
    default_spec = InMemoryDatabaseSpec(
        schema_metadata=schema_metadata,
        query_rows=[
            {"id": "1", "name": "Ada", "email": "ada@example.com"},
            {"id": "2", "name": "Linus", "email": "linus@example.com"},
        ],
    )
    mcp_client = LocalMCPServerClient(
        databases={database_id: default_spec},
        default_database_spec=default_spec,
        allow_implicit_databases=True,
    )
    planner = query_planner or OllamaQueryPlanner(resolved_settings, fallback_planner=HeuristicQueryPlanner())
    return DatabaseOrchestrator(
        mcp_client=mcp_client,
        schema_cache=SchemaCache(),
        schema_inspector=MCPBackedSchemaInspector(mcp_client),
        query_planner=planner,
        query_validator=QueryValidator(),
        result_formatter=DefaultResultFormatter(),
        audit_logger=ConsoleAuditLogger(),
    )


def build_runtime_orchestrator(settings: AppSettings | None = None, query_planner: QueryPlanner | None = None) -> DatabaseOrchestrator:
    resolved_settings = settings or AppSettings.from_env()
    print(f"Building runtime orchestrator with settings: {resolved_settings}")
    planner = query_planner or OllamaQueryPlanner(resolved_settings, fallback_planner=HeuristicQueryPlanner())
    if resolved_settings.mcp_server_url:
        mcp_client = HTTPMCPServerClient(
            base_url=resolved_settings.mcp_server_url,
            api_key=resolved_settings.mcp_api_key,
            instantiate_path=resolved_settings.mcp_instantiate_path,
            schema_path=resolved_settings.mcp_schema_path,
            query_path=resolved_settings.mcp_query_path,
            release_path=resolved_settings.mcp_release_path,
        )
        schema_inspector = MCPBackedSchemaInspector(mcp_client)
    else:
        database_id = resolved_settings.demo_database_id
        schema_metadata = build_demo_schema(database_id, resolved_settings.schema_cache_ttl_seconds)
        default_spec = InMemoryDatabaseSpec(
            schema_metadata=schema_metadata,
            query_rows=[
                {"id": "1", "name": "Ada", "email": "ada@example.com"},
                {"id": "2", "name": "Linus", "email": "linus@example.com"},
            ],
        )
        mcp_client = HTTPMCPServerClient(
            base_url=resolved_settings.mcp_server_url,
            instantiate_path=resolved_settings.mcp_instantiate_path,
            schema_path=resolved_settings.mcp_schema_path,
            query_path=resolved_settings.mcp_query_path,
            release_path=resolved_settings.mcp_release_path,
        )
        schema_inspector = MCPBackedSchemaInspector(mcp_client)

    return DatabaseOrchestrator(
        mcp_client=mcp_client,
        schema_cache=SchemaCache(),
        schema_inspector=schema_inspector,
        query_planner=planner,
        query_validator=QueryValidator(),
        result_formatter=DefaultResultFormatter(),
        audit_logger=ConsoleAuditLogger(),
    )


def create_server(settings: AppSettings | None = None, query_planner: QueryPlanner | None = None) -> AgentHTTPServer:
    resolved_settings = settings or AppSettings.from_env()
    orchestrator = build_runtime_orchestrator(resolved_settings, query_planner=query_planner)
    server = AgentHTTPServer((resolved_settings.http_host, resolved_settings.http_port), AgentRequestHandler, orchestrator, resolved_settings)
    server.authenticator = ApiKeyAuthenticator(resolved_settings.http_api_key)  # type: ignore[attr-defined]
    return server


def run_http_server(settings: AppSettings | None = None) -> None:
    resolved_settings = settings or AppSettings.from_env()
    server = create_server(resolved_settings)
    print(f"HTTP server listening on http://{resolved_settings.http_host}:{resolved_settings.http_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.orchestrator.close_all_databases()
        server.server_close()


def main() -> None:
    run_http_server()


if __name__ == "__main__":
    main()
