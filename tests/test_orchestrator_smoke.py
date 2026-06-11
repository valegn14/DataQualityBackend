from __future__ import annotations

from datetime import datetime, timezone

from data_analysis_backend.contracts import (
    AgentRequest,
    ColumnMetadata,
    RelationMetadata,
    SchemaMetadata,
    TableMetadata,
)
from data_analysis_backend.default_components import ConsoleAuditLogger, DefaultResultFormatter, StaticQueryPlanner
from data_analysis_backend.mcp_client import InMemoryDatabaseSpec, LocalMCPServerClient
from data_analysis_backend.mcp_schema_inspector import MCPBackedSchemaInspector
from data_analysis_backend.orchestrator import DatabaseOrchestrator
from data_analysis_backend.schema_cache import SchemaCache
from data_analysis_backend.validator import QueryValidator


def test_orchestrator_smoke() -> None:
    database_id = "db-1"
    schema_metadata = SchemaMetadata(
        database_id=database_id,
        schema_version="v1",
        fetched_at=datetime.now(timezone.utc),
        ttl_seconds=60,
        dialect="postgresql",
        tables=[
            TableMetadata(
                name="customers",
                columns=[ColumnMetadata(name="id", type="uuid", nullable=False, is_primary_key=True)],
                primary_key=["id"],
                is_view=False,
            )
        ],
        relations=[RelationMetadata("customers", "id", "orders", "customer_id")],
    )
    client = LocalMCPServerClient(
        databases={
            database_id: InMemoryDatabaseSpec(
                schema_metadata=schema_metadata,
                query_rows=[{"customer_id": 1, "name": "Ada"}],
            )
        }
    )
    orchestrator = DatabaseOrchestrator(
        mcp_client=client,
        schema_cache=SchemaCache(),
        schema_inspector=MCPBackedSchemaInspector(client),
        query_planner=StaticQueryPlanner(),
        query_validator=QueryValidator(),
        result_formatter=DefaultResultFormatter(),
        audit_logger=ConsoleAuditLogger(),
    )

    request = AgentRequest(
        request_id="req-1",
        user_id="user-1",
        prompt="show customers",
        database_id="db-1",
    )

    result = orchestrator.execute(request)

    assert result.validation.is_valid is True
    assert result.result is not None
    assert result.result.row_count == 1
    assert result.formatted_result is not None
    assert result.formatted_result["row_count"] == 1
