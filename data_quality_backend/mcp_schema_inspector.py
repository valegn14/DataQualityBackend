from __future__ import annotations

from .contracts import DatabaseHandle, SchemaMetadata
from .mcp_client import MCPServerClient
from .schema_inspector import SchemaInspector


class MCPBackedSchemaInspector(SchemaInspector):
    def __init__(self, mcp_client: MCPServerClient) -> None:
        self._mcp_client = mcp_client

    def load_schema(self, database_handle: DatabaseHandle) -> SchemaMetadata:
        return self._mcp_client.fetch_schema(database_handle)
