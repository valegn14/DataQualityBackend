from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from .contracts import AgentRequest, DatabaseHandle, PlannerAction, QueryResult, SchemaMetadata
from .mcp_client import MCPServerClient
from .schema_cache import SchemaCache
from .schema_inspector import SchemaInspector
from .validator import QueryValidator, ValidationResult


class QueryPlanner(Protocol):
    def build_action(
        self,
        prompt: str,
        schema_metadata: SchemaMetadata,
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
    sql: str | None
    validation: ValidationResult
    result: QueryResult | None
    formatted_result: dict[str, object] | None
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
    ) -> None:
        self._mcp_client = mcp_client
        self._schema_cache = schema_cache
        self._schema_inspector = schema_inspector
        self._query_planner = query_planner
        self._query_validator = query_validator
        self._result_formatter = result_formatter
        self._audit_logger = audit_logger

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

        emit("Instanciando base de datos")
        database_handle = self._mcp_client.instantiate_database(
            request.database_id
        )

        try:
            schema_metadata = self._schema_cache.get(
                request.database_id
            )

            if schema_metadata is None:
                self._audit_logger.log_schema_miss(
                    request.database_id
                )
                emit("Leyendo esquema desde MCP")

                schema_metadata = (
                    self._schema_inspector.load_schema(
                        database_handle
                    )
                )

                self._schema_cache.put(
                    request.database_id,
                    schema_metadata,
                )
            else:
                self._audit_logger.log_schema_hit(
                    request.database_id
                )
                emit("Usando esquema en caché")

            max_attempts = getattr(request, "max_attempts", 3)

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

            while attempt < max_attempts:
                attempt += 1

                emit(f"Intento {attempt} de {max_attempts}")

                action = self._query_planner.build_action(
                    prompt=request.prompt,
                    schema_metadata=schema_metadata,
                    previous_queries=query_history,
                    previous_results=result_history,
                    assistant_history=assistant_history,
                )

                last_sql = action.sql

                if action.comment:
                    assistant_history.append(action.comment)

                if action.action == "analysis":
                    emit("Análisis recibido del agente")
                    if not action.sql and attempt >= max_attempts:
                        emit("No se ejecutó consulta y se alcanzó el límite de intentos")
                        break
                    continue

                if action.action == "execute":
                    if not action.sql:
                        emit("No se encontró SQL para ejecutar")
                        break

                    validation = self._query_validator.validate(
                        action.sql,
                        schema_metadata,
                        request.allow_write,
                    )
                    last_validation = validation

                    if not validation.is_valid:
                        emit("Consulta no válida: " + "; ".join(validation.reasons))
                        break

                    emit("Ejecutando consulta")
                    self._audit_logger.log_query(action.sql)

                    rows = self._mcp_client.send_query(
                        database_handle,
                        action.sql,
                    )

                    max_rows = (
                        request.max_rows
                        if isinstance(request.max_rows, int)
                        else 100
                    )

                    result = QueryResult(
                        rows=rows,
                        row_count=len(rows),
                        truncated=len(rows) > max_rows,
                    )

                    query_history.append(action.sql)
                    executed_queries.append(action.sql)
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
                    continue

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
                sql=last_sql,
                validation=last_validation,
                result=last_result,
                formatted_result=last_formatted,
                assistant_history=assistant_history,
                executed_queries=executed_queries,
                final_comment=final_comment,
                progress=progress_messages,
            )

        finally:
            self._mcp_client.release_database(
                database_handle
            )