from __future__ import annotations

from dataclasses import asdict

from .contracts import AgentRequest, PlannerAction, QueryResult, SchemaMetadata
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
    def build_action(
        self,
        prompt: str,
        schema_metadata: dict[str, SchemaMetadata],
        previous_queries: list[str] | None = None,
        previous_results: list[QueryResult] | None = None,
        assistant_history: list[str] | None = None,
        sample_data: list[dict] | None = None,
    ) -> PlannerAction:
        _ = asdict(next(iter(schema_metadata.values())))
        return super().build_action(
            prompt,
            schema_metadata,
            previous_queries=previous_queries,
            previous_results=previous_results,
            assistant_history=assistant_history,
            sample_data=sample_data,
        )
