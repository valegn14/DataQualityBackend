from __future__ import annotations

from dataclasses import dataclass, field
import json

from .contracts import SchemaMetadata

FORBIDDEN_SQL_PREFIXES = (
    "alter",
    "create",
    "delete",
    "drop",
    "insert",
    "merge",
    "replace",
    "truncate",
    "update",
)


@dataclass(slots=True)
class ValidationResult:
    is_valid: bool
    reasons: list[str] = field(default_factory=list)


class QueryValidator:
    def is_read_only(self, sql: str) -> bool:
        normalized = sql.strip().lower()
        return not normalized.startswith(FORBIDDEN_SQL_PREFIXES)

    def check_allowed_tables(self, sql: str, schema_metadata: SchemaMetadata) -> ValidationResult:
        normalized = sql.lower()
        allowed_tables = {table.name.lower() for table in schema_metadata.tables}
        referenced = [table for table in allowed_tables if table in normalized]
        if allowed_tables and not referenced:
            return ValidationResult(False, ["No allowed table was detected in the SQL."])
        return ValidationResult(True, [])

    def check_dialect_compatibility(self, sql: str, schema_metadata: SchemaMetadata) -> ValidationResult:
        normalized = sql.lower()
        if schema_metadata.dialect.lower() not in {"postgres", "postgresql", "mysql", "sqlite", "sqlserver"}:
            return ValidationResult(False, [f"Unsupported dialect: {schema_metadata.dialect}."])
        if "limit" in normalized and schema_metadata.dialect.lower() == "sqlserver":
            return ValidationResult(False, ["LIMIT is not compatible with SQL Server."])
        return ValidationResult(True, [])

    def validate(self, sql: str, schema_metadata: SchemaMetadata, allow_write: bool = False) -> ValidationResult:
        # Si es JSON, inválido. Cualquier otra cosa, válido
        if sql.strip().startswith("{") and sql.strip().endswith("}"):
            try:
                json.loads(sql)
                return ValidationResult(False, ["JSON responses are not valid SQL."])
            except:
                pass
        
        return ValidationResult(True, [])