from __future__ import annotations

import os
from dataclasses import dataclass


def _get_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


@dataclass(slots=True)
class AppSettings:
    # -------------------------
    # LLM CONFIG
    # -------------------------
    llm_provider: str = "ollama"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "phi4-mini"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "phi4-mini"
    ollama_timeout_seconds: int = 300
    ollama_allow_fallback: bool = True

    # -------------------------
    # MCP CONFIG
    # -------------------------
    mcp_transport: str = "http"

    # FIX: nunca None sin fallback
    mcp_server_url: str = "http://127.0.0.1:8001"

    mcp_api_key: str | None = None

    # FIX: rutas alineadas con tu MCP real
    mcp_instantiate_path: str = "/mcp/instantiate_database"
    mcp_schema_path: str = "/mcp/fetch_schema"
    mcp_query_path: str = "/mcp/send_query"
    mcp_release_path: str = "/mcp/release_database"

    # -------------------------
    # CACHE / EXECUTION
    # -------------------------
    schema_cache_ttl_seconds: int = 300
    default_max_rows: int = 100
    allow_write_default: bool = False

    # -------------------------
    # HTTP SERVER
    # -------------------------
    http_host: str = "127.0.0.1"
    http_port: int = 8000
    http_api_key: str | None = None

    demo_database_id: str = "demo-db"

    @classmethod
    def from_env(cls) -> "AppSettings":
        defaults = cls()

        return cls(
            # LLM
            llm_provider=os.getenv("LLM_PROVIDER", defaults.llm_provider),
            llm_api_key=os.getenv("LLM_API_KEY"),
            llm_base_url=os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434"),
            llm_model=os.getenv("LLM_MODEL", defaults.llm_model),

            # Ollama
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", defaults.ollama_base_url),
            ollama_model=os.getenv("OLLAMA_MODEL", defaults.ollama_model),
            ollama_timeout_seconds=_get_int("OLLAMA_TIMEOUT_SECONDS", defaults.ollama_timeout_seconds),
            ollama_allow_fallback=_get_bool("OLLAMA_ALLOW_FALLBACK", defaults.ollama_allow_fallback),

            # MCP
            mcp_transport=os.getenv("MCP_TRANSPORT", defaults.mcp_transport),

            # FIX: fallback real
            mcp_server_url=_get_str("MCP_SERVER_URL", defaults.mcp_server_url),

            mcp_api_key=os.getenv("MCP_API_KEY"),

            # Cache
            schema_cache_ttl_seconds=_get_int(
                "SCHEMA_CACHE_TTL_SECONDS",
                defaults.schema_cache_ttl_seconds
            ),
            default_max_rows=_get_int(
                "DEFAULT_MAX_ROWS",
                defaults.default_max_rows
            ),
            allow_write_default=_get_bool(
                "ALLOW_WRITE_DEFAULT",
                defaults.allow_write_default
            ),

            # HTTP server
            http_host=os.getenv("HTTP_HOST", defaults.http_host),
            http_port=_get_int("HTTP_PORT", defaults.http_port),
            http_api_key=os.getenv("HTTP_API_KEY"),

            demo_database_id=os.getenv("DEMO_DATABASE_ID", defaults.demo_database_id),
        )