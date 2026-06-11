from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import DatabaseHandle, SchemaMetadata
from .mcp_client import MCPServerClient


class HTTPMCPServerClient(MCPServerClient):
    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        instantiate_path: str = "/instantiate",
        schema_path: str = "/schema",
        query_path: str = "/query",
        release_path: str = "/release",
        timeout_seconds: int = 30,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key.strip() if api_key else None
        self._instantiate_path = instantiate_path
        self._schema_path = schema_path
        self._query_path = query_path
        self._release_path = release_path
        self._timeout_seconds = timeout_seconds

    def instantiate_database(self, database_id: str) -> DatabaseHandle:
        print(f"HTTPMCPServerClient: Instantiating database with database_id='{database_id}' at base_url='{self._base_url}'")
        try:
            payload = self._request("POST", self._instantiate_path, {"database_id": database_id})
        except RuntimeError as exc:
            if not self._is_422(exc):
                raise
            payload = self._request("POST", self._instantiate_path, {"dataset_id": database_id})
        return self._handle_from_payload(payload, database_id)

    def fetch_schema(self, database_handle: DatabaseHandle) -> SchemaMetadata:
        try:
            payload = self._request("POST", self._schema_path, {"database_handle": asdict(database_handle)})
        except RuntimeError as exc:
            if not self._is_422(exc):
                raise
            payload = self._request("POST", self._schema_path, {"handle_id": database_handle.handle_id})
        return self._schema_from_payload(payload, database_handle.database_id)

    def send_query(self, database_handle: DatabaseHandle, sql: str) -> list[dict[str, object]]:
        try:
            payload = self._request(
                "POST",
                self._query_path,
                {"database_handle": asdict(database_handle), "sql": sql},
            )
        except RuntimeError as exc:
            if not self._is_422(exc):
                raise
            payload = self._request(
                "POST",
                self._query_path,
                {"handle_id": database_handle.handle_id, "sql": sql},
            )
        if isinstance(payload.get("error"), str):
            message = str(payload.get("message") or payload["error"])
            raise RuntimeError(f"MCP query failed: {message}")
        rows = payload.get("rows")
        if isinstance(rows, list):
            return rows
        result = payload.get("result")
        return result if isinstance(result, list) else []

    def release_database(self, database_handle: DatabaseHandle) -> None:
        try:
            self._request("POST", self._release_path, {"database_handle": asdict(database_handle)})
        except Exception:
            try:
                self._request("POST", self._release_path, {"handle_id": database_handle.handle_id})
            except Exception:
                return

    def _request(self, method: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        data = json.dumps(payload, default=self._json_default).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = Request(f"{self._base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"MCP request failed: {exc}") from exc
        parsed = json.loads(body) if body else {}
        return parsed if isinstance(parsed, dict) else {}

    def _handle_from_payload(self, payload: dict[str, object], database_id: str) -> DatabaseHandle:
        handle_id = str(payload.get("handle_id") or payload.get("id") or f"handle-{database_id}")
        instance_id = str(payload.get("instance_id") or payload.get("instanceId") or f"instance-{database_id}")
        dialect = str(payload.get("dialect") or "postgresql")
        expires_at = datetime.now(timezone.utc)
        return DatabaseHandle(
            handle_id=handle_id,
            database_id=database_id,
            instance_id=instance_id,
            dialect=dialect,
            expires_at=expires_at,
        )

    def _schema_from_payload(self, payload: dict[str, object], database_id: str) -> SchemaMetadata:
        from .contracts import ColumnMetadata, RelationMetadata, SchemaMetadata as SchemaMetadataModel, TableMetadata

        schema_payload = payload.get("schema_metadata") if isinstance(payload.get("schema_metadata"), dict) else payload
        tables: list[TableMetadata] = []
        for table_payload in schema_payload.get("tables", []) if isinstance(schema_payload.get("tables"), list) else []:
            if not isinstance(table_payload, dict):
                continue
            columns: list[ColumnMetadata] = []
            for column_payload in table_payload.get("columns", []) if isinstance(table_payload.get("columns"), list) else []:
                if not isinstance(column_payload, dict):
                    continue
                columns.append(
                    ColumnMetadata(
                        name=str(column_payload.get("name", "")),
                        type=str(column_payload.get("type", "text")),
                        nullable=bool(column_payload.get("nullable", True)),
                        is_primary_key=bool(column_payload.get("is_primary_key", False)),
                        is_foreign_key=bool(column_payload.get("is_foreign_key", False)),
                    )
                )
            tables.append(
                TableMetadata(
                    name=str(table_payload.get("name", "")),
                    columns=columns,
                    primary_key=[str(value) for value in table_payload.get("primary_key", [])] if isinstance(table_payload.get("primary_key"), list) else [],
                    is_view=bool(table_payload.get("is_view", False)),
                )
            )

        relations: list[RelationMetadata] = []
        for relation_payload in schema_payload.get("relations", []) if isinstance(schema_payload.get("relations"), list) else []:
            if not isinstance(relation_payload, dict):
                continue
            relations.append(
                RelationMetadata(
                    source_table=str(relation_payload.get("source_table", "")),
                    source_column=str(relation_payload.get("source_column", "")),
                    target_table=str(relation_payload.get("target_table", "")),
                    target_column=str(relation_payload.get("target_column", "")),
                )
            )

        indexes = schema_payload.get("indexes", []) if isinstance(schema_payload.get("indexes"), list) else []

        return SchemaMetadataModel(
            database_id=database_id,
            schema_version=str(schema_payload.get("schema_version")) if schema_payload.get("schema_version") else None,
            fetched_at=datetime.now(timezone.utc),
            ttl_seconds=int(schema_payload.get("ttl_seconds") or 300),
            dialect=str(schema_payload.get("dialect") or "postgresql"),
            tables=tables,
            relations=relations,
            indexes=[item for item in indexes if isinstance(item, dict)],
        )

    def _json_default(self, value: object) -> object:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def _is_422(self, exc: RuntimeError) -> bool:
        return "422" in str(exc)