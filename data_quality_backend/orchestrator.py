from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .contracts import AgentRequest, DatabaseHandle, PlannerAction, QueryResult, SchemaMetadata
from .settings import AppSettings
from .mcp_client import MCPServerClient
from .schema_cache import SchemaCache
from .schema_inspector import SchemaInspector
from .validator import QueryValidator, ValidationResult


class QueryPlanner(Protocol):
    def build_action(
        self,
        prompt: str,
        schema_metadata: dict[str, SchemaMetadata],
        previous_queries: list[str] | None = None,
        previous_results: list[QueryResult] | None = None,
        assistant_history: list[str] | None = None,
    ) -> PlannerAction:
        raise NotImplementedError


class ResultFormatter(Protocol):
    def format(self, result: QueryResult) -> dict[str, object]:
        raise NotImplementedError


class AuditLogger(Protocol):
    def log_request(self, request: AgentRequest) -> None:
        raise NotImplementedError

    def log_progress(self, message: str) -> None:
        raise NotImplementedError

    def log_schema_hit(self, database_id: str) -> None:
        raise NotImplementedError

    def log_schema_miss(self, database_id: str) -> None:
        raise NotImplementedError

    def log_query(self, sql: str) -> None:
        raise NotImplementedError

    def log_result(self, metadata: dict[str, object]) -> None:
        raise NotImplementedError


@dataclass(slots=True)
class OrchestrationResult:
    request_id: str
    database_id: str
    database_ids: list[str] | None
    sql: list[str] | None
    intent: str | None
    plan_steps: list[dict[str, object]] | None
    validation: ValidationResult
    result: QueryResult | None
    formatted_result: dict[str, object] | None
    context: dict[str, object] | None = None
    assistant_history: list[str] = field(default_factory=list)
    executed_queries: list[str] = field(default_factory=list)
    final_comment: str | None = None
    progress: list[str] = field(default_factory=list)


class DatabaseOrchestrator:
    def __init__(
        self,
        mcp_client: MCPServerClient,
        schema_cache: SchemaCache,
        schema_inspector: SchemaInspector,
        query_planner: QueryPlanner,
        query_validator: QueryValidator,
        result_formatter: ResultFormatter,
        audit_logger: AuditLogger,
        settings: AppSettings | None = None,
    ) -> None:
        self._mcp_client = mcp_client
        self._schema_cache = schema_cache
        self._schema_inspector = schema_inspector
        self._query_planner = query_planner
        self._query_validator = query_validator
        self._result_formatter = result_formatter
        self._audit_logger = audit_logger
        self._settings = settings or AppSettings.from_env()
        self._database_handles: dict[str, DatabaseHandle] = {}

    def _get_database_handle(self, dataset_id: str) -> DatabaseHandle:
        if dataset_id in self._database_handles:
            return self._database_handles[dataset_id]

        handle = self._mcp_client.instantiate_database(dataset_id)
        self._database_handles[dataset_id] = handle
        return handle

    def close_all_databases(self) -> None:
        for handle in list(self._database_handles.values()):
            try:
                self._mcp_client.release_database(handle)
            except Exception as exc:
                self._audit_logger.log_progress(f"No se pudo liberar el handle {handle.database_id}: {exc}")
        self._database_handles.clear()

    def execute(
        self,
        request: AgentRequest,
        progress_callback: Callable[[str], None] | None = None,
    ) -> OrchestrationResult:
        progress_messages: list[str] = []

        def emit(message: str) -> None:
            progress_messages.append(message)
            self._audit_logger.log_progress(message)
            if progress_callback is not None:
                progress_callback(message)

        emit("Recibido pedido")
        self._audit_logger.log_request(request)

        emit("Obteniendo instancias de base de datos")
        database_ids = request.database_ids or [request.database_id]
        schema_map: dict[str, SchemaMetadata] = {}

        for dataset_id in database_ids:
            handle = self._get_database_handle(dataset_id)
            schema_metadata = self._schema_cache.get(dataset_id)

            if schema_metadata is None:
                self._audit_logger.log_schema_miss(dataset_id)
                emit(f"Leyendo esquema desde MCP para {dataset_id}")
                schema_metadata = self._schema_inspector.load_schema(handle)
                self._schema_cache.put(dataset_id, schema_metadata)
            else:
                self._audit_logger.log_schema_hit(dataset_id)
                emit(f"Usando esquema en caché para {dataset_id}")

            schema_map[dataset_id] = schema_metadata

        max_attempts = request.max_attempts if isinstance(request.max_attempts, int) else self._settings.max_planner_attempts

        attempt = 0

        last_result = None
        last_formatted = None
        last_sql = None
        last_validation = ValidationResult(True, [])
        final_comment: str | None = None
        query_history: list[str] = []
        result_history: list[QueryResult] = []
        assistant_history: list[str] = list(request.assistant_context)
        executed_queries: list[str] = []

        try:
            while attempt < max_attempts:
                attempt += 1

                emit(f"Intento {attempt} de {max_attempts}")

                action = self._query_planner.build_action(
                    prompt=request.prompt,
                    schema_metadata=schema_map,
                    previous_queries=query_history,
                    previous_results=result_history,
                    assistant_history=assistant_history,
                )

                last_sql = action.sql

                if action.comment:
                    assistant_history.append(action.comment)

                if action.action == "plan":
                    emit("Plan de trabajo recibido del agente")
                    return OrchestrationResult(
                        request_id=request.request_id,
                        database_id=request.database_id,
                        database_ids=database_ids,
                        sql=last_sql,
                        intent=action.intent,
                        plan_steps=action.plan_steps,
                        validation=last_validation,
                        result=None,
                        formatted_result=None,
                        context={
                            "dataset_ids": database_ids,
                            "selected_dataset": action.dataset_id,
                            "previous_query_count": len(query_history),
                        },
                        assistant_history=assistant_history,
                        executed_queries=executed_queries,
                        final_comment=action.comment,
                        progress=progress_messages,
                    )

                if action.action == "analysis":
                    emit("Análisis recibido del agente")
                    if not action.sql:
                        if attempt >= max_attempts:
                            emit("No se ejecutó consulta y se alcanzó el límite de intentos")
                            break
                        continue
                    # If analysis carries SQL, try to execute it.

                if action.action == "execute":
                    if not action.sql:
                        emit("No se encontró SQL para ejecutar")
                        break

                    target_dataset_id = action.dataset_id or database_ids[0]
                    if target_dataset_id not in schema_map:
                        emit(f"Dataset desconocido: {target_dataset_id}")
                        break

                    database_handle = self._get_database_handle(target_dataset_id)
                    target_schema = schema_map[target_dataset_id]

                    stmts: list[str] = action.sql if isinstance(action.sql, list) else [action.sql]

                    for stmt in stmts:
                        if not stmt or not isinstance(stmt, str):
                            emit("Consulta vacía u no válida recibida del planner")
                            continue

                        validation = self._query_validator.validate(
                            stmt,
                            target_schema,
                            request.allow_write,
                        )
                        last_validation = validation

                        if not validation.is_valid:
                            emit("Consulta no válida: " + "; ".join(validation.reasons))
                            break

                        emit("Ejecutando consulta en dataset " + target_dataset_id)
                        self._audit_logger.log_query(stmt)

                        rows = self._mcp_client.send_query(
                            database_handle,
                            stmt,
                        )

                        max_rows = (
                            request.max_rows
                            if isinstance(request.max_rows, int)
                            else self._settings.default_max_rows
                        )

                        result = QueryResult(
                            rows=rows,
                            row_count=len(rows),
                            truncated=len(rows) > max_rows,
                        )

                        query_history.append(stmt)
                        executed_queries.append(stmt)
                        result_history.append(result)

                        emit("Formateando resultado")
                        formatted_result = self._result_formatter.format(result)
                        self._audit_logger.log_result(
                            {
                                "row_count": result.row_count,
                                "truncated": result.truncated,
                            }
                        )

                        last_result = result
                        last_formatted = formatted_result
                        last_validation = validation

                    return OrchestrationResult(
                        request_id=request.request_id,
                        database_id=request.database_id,
                        database_ids=database_ids,
                        sql=last_sql,
                        intent=action.intent,
                        plan_steps=action.plan_steps,
                        validation=last_validation,
                        result=last_result,
                        formatted_result=last_formatted,
                        context={
                            "dataset_ids": database_ids,
                            "selected_dataset": target_dataset_id,
                            "previous_query_count": len(query_history),
                        },
                        assistant_history=assistant_history,
                        executed_queries=executed_queries,
                        final_comment=action.comment,
                        progress=progress_messages,
                    )

                if action.action == "final":
                    emit("Agente finalizó el razonamiento")
                    final_comment = action.comment
                    break

                emit(f"Acción desconocida recibida: {action.action}")
                break

            emit("Listo")

            return OrchestrationResult(
                request_id=request.request_id,
                database_id=request.database_id,
                database_ids=database_ids,
                sql=last_sql,
                intent=None,
                plan_steps=None,
                validation=last_validation,
                result=last_result,
                formatted_result=last_formatted,
                context={
                    "dataset_ids": database_ids,
                    "previous_query_count": len(query_history),
                },
                assistant_history=assistant_history,
                executed_queries=executed_queries,
                final_comment=final_comment,
                progress=progress_messages,
            )
        finally:
            pass
