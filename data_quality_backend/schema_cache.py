from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from .contracts import SchemaMetadata


class SchemaCache:
    def __init__(self) -> None:
        self._items: dict[str, SchemaMetadata] = {}

    def get(self, database_id: str) -> SchemaMetadata | None:
        schema = self._items.get(database_id)
        if schema is None:
            return None
        if self.is_expired(database_id):
            self.invalidate(database_id)
            return None
        return schema

    def put(self, database_id: str, schema_metadata: SchemaMetadata) -> None:
        self._items[database_id] = schema_metadata

    def invalidate(self, database_id: str) -> None:
        self._items.pop(database_id, None)

    def is_expired(self, database_id: str) -> bool:
        schema = self._items.get(database_id)
        if schema is None:
            return True
        now = datetime.now(timezone.utc)
        age_seconds = (now - schema.fetched_at).total_seconds()
        return age_seconds >= schema.ttl_seconds

    def refresh_ttl(self, database_id: str, ttl_seconds: int) -> SchemaMetadata | None:
        schema = self._items.get(database_id)
        if schema is None:
            return None
        updated = replace(schema, ttl_seconds=ttl_seconds)
        self._items[database_id] = updated
        return updated
