from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AuthContext:
    principal_id: str
    roles: tuple[str, ...] = ()


class AuthError(Exception):
    pass


class ApiKeyAuthenticator:
    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key.strip() if api_key else None

    def is_enabled(self) -> bool:
        return bool(self._api_key)

    def authenticate(self, headers: dict[str, str]) -> AuthContext:
        if not self._api_key:
            return AuthContext(principal_id="anonymous")

        provided = headers.get("Authorization", "")
        if provided.startswith("Bearer "):
            provided = provided.removeprefix("Bearer ").strip()
        elif headers.get("X-API-Key"):
            provided = headers.get("X-API-Key", "").strip()

        if provided != self._api_key:
            raise AuthError("Unauthorized")

        return AuthContext(principal_id="api-key-client")