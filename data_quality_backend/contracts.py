from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class AgentRequest:
    request_id: str
    user_id: str
    prompt: str
    database_id: str
    allow_write: bool = False
    max_rows: int = 100
    preferred_dialect: str | None = None
    assistant_context: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DatabaseHandle:
    handle_id: str
    database_id: str
    instance_id: str
    dialect: str
    expires_at: datetime


@dataclass(slots=True)
class ColumnMetadata:
    name: str
    type: str
    nullable: bool
    is_primary_key: bool = False
    is_foreign_key: bool = False


@dataclass(slots=True)
class TableMetadata:
    name: str
    columns: list[ColumnMetadata] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    is_view: bool = False


@dataclass(slots=True)
class RelationMetadata:
    source_table: str
    source_column: str
    target_table: str
    target_column: str


@dataclass(slots=True)
class SchemaMetadata:
    database_id: str
    schema_version: str | None
    fetched_at: datetime
    ttl_seconds: int
    dialect: str
    tables: list[TableMetadata] = field(default_factory=list)
    relations: list[RelationMetadata] = field(default_factory=list)
    indexes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class QueryResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlannerAction:
    action: str
    sql: list[str] | None = None
    comment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
