from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .contracts import DatabaseHandle, SchemaMetadata


@dataclass(slots=True)
class InMemoryDatabaseSpec:
    schema_metadata: SchemaMetadata
    query_rows: list[dict[str, object]] = field(default_factory=list)


class MCPServerClient(ABC):
    @abstractmethod
    def instantiate_database(self, database_id: str) -> DatabaseHandle:
        raise NotImplementedError

    @abstractmethod
    def fetch_schema(self, database_handle: DatabaseHandle) -> SchemaMetadata:
        raise NotImplementedError

    @abstractmethod
    def send_query(self, database_handle: DatabaseHandle, sql: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @abstractmethod
    def release_database(self, database_handle: DatabaseHandle) -> None:
        raise NotImplementedError


class MCPDatabaseClient(ABC):
    @abstractmethod
    def connect(self, database_ref: str) -> DatabaseHandle:
        raise NotImplementedError

    @abstractmethod
    def query(self, database_handle: DatabaseHandle, sql: str) -> list[dict[str, object]]:
        raise NotImplementedError

    @abstractmethod
    def close(self, database_handle: DatabaseHandle) -> None:
        raise NotImplementedError


class LocalMCPServerClient(MCPServerClient):
    def __init__(
        self,
        databases: dict[str, InMemoryDatabaseSpec] | None = None,
        default_database_spec: InMemoryDatabaseSpec | None = None,
        allow_implicit_databases: bool = False,
    ) -> None:
        self._databases = databases or {}
        self._default_database_spec = default_database_spec
        self._allow_implicit_databases = allow_implicit_databases
        self._active_handles: dict[str, str] = {}

    def instantiate_database(self, database_id: str) -> DatabaseHandle:
        spec = self._resolve_spec(database_id)
        if spec is None:
            raise KeyError(f"Unknown database_id: {database_id}")

        handle_id = f"handle-{uuid4().hex}"
        instance_id = f"instance-{uuid4().hex}"
        self._active_handles[handle_id] = database_id
        return DatabaseHandle(
            handle_id=handle_id,
            database_id=database_id,
            instance_id=instance_id,
            dialect=spec.schema_metadata.dialect,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )

    def fetch_schema(self, database_handle: DatabaseHandle) -> SchemaMetadata:
        return self._get_spec(database_handle).schema_metadata

    def send_query(self, database_handle: DatabaseHandle, sql: str) -> list[dict[str, object]]:
        spec = self._get_spec(database_handle)
        if not spec.query_rows:
            return [{"sql": sql, "database_id": database_handle.database_id}]
        return spec.query_rows

    def release_database(self, database_handle: DatabaseHandle) -> None:
        self._active_handles.pop(database_handle.handle_id, None)

    def _get_spec(self, database_handle: DatabaseHandle) -> InMemoryDatabaseSpec:
        database_id = self._active_handles.get(database_handle.handle_id)
        if database_id is None:
            raise KeyError(f"Unknown handle_id: {database_handle.handle_id}")
        spec = self._resolve_spec(database_id)
        if spec is None:
            raise KeyError(f"Unknown database_id: {database_id}")
        return spec

    def _resolve_spec(self, database_id: str) -> InMemoryDatabaseSpec | None:
        spec = self._databases.get(database_id)
        if spec is not None:
            return spec
        if self._allow_implicit_databases and self._default_database_spec is not None:
            self._databases[database_id] = self._default_database_spec
            return self._default_database_spec
        return None


class LocalMCPDatabaseClient(MCPDatabaseClient):
    def __init__(self, server_client: LocalMCPServerClient) -> None:
        self._server_client = server_client

    def connect(self, database_ref: str) -> DatabaseHandle:
        return self._server_client.instantiate_database(database_ref)

    def query(self, database_handle: DatabaseHandle, sql: str) -> list[dict[str, object]]:
        return self._server_client.send_query(database_handle, sql)

    def close(self, database_handle: DatabaseHandle) -> None:
        self._server_client.release_database(database_handle)
