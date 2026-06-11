from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import DatabaseHandle, SchemaMetadata


class SchemaInspector(ABC):
    @abstractmethod
    def load_schema(self, database_handle: DatabaseHandle) -> SchemaMetadata:
        raise NotImplementedError
