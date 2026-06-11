from __future__ import annotations

from dataclasses import asdict

from .contracts import AgentRequest, QueryResult, SchemaMetadata
from .planner import HeuristicQueryPlanner


class DefaultResultFormatter:
    def format(self, result: QueryResult) -> dict[str, object]:
        return {
            "row_count": result.row_count,
            "truncated": result.truncated,
            "rows": result.rows,
            "metadata": result.metadata,
        }


class ConsoleAuditLogger:
    def log_request(self, request: AgentRequest) -> None:
        print(f"request={request.request_id} database={request.database_id}")

    def log_progress(self, message: str) -> None:
        print(f"progress={message}")

    def log_schema_hit(self, database_id: str) -> None:
        print(f"schema_hit database={database_id}")

    def log_schema_miss(self, database_id: str) -> None:
        print(f"schema_miss database={database_id}")

    def log_query(self, sql: str) -> None:
        print(f"sql={sql}")

    def log_result(self, metadata: dict[str, object]) -> None:
        print(f"result={metadata}")


class StaticQueryPlanner(HeuristicQueryPlanner):
    def build_sql(self, prompt: str, schema_metadata: SchemaMetadata) -> str:
        _ = asdict(schema_metadata)
        return super().build_sql(prompt, schema_metadata)
