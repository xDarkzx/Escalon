"""Entra ID bearer-token validation for the MCP server and the HTTP API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken

REQUIRED_SCOPE = "Helpdesk.Use"


def entra_issuers(tenant_id: str) -> list[str]:
    # v2.0 tokens, and v1.0 tokens for apps whose manifest still requests them.
    return [f"https://login.microsoftonline.com/{tenant_id}/v2.0", f"https://sts.windows.net/{tenant_id}/"]


def entra_jwks_url(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"


class EntraTokenVerifier:
    """Validates signature, issuer, audience, expiry and the delegated scope.

    ``signing_key`` maps a raw token to its public key; by default it is fetched (and cached)
    from the tenant's JWKS endpoint.
    """

    def __init__(
        self,
        tenant_id: str,
        audience: str,
        signing_key: Callable[[str], Any] | None = None,
    ) -> None:
        self._issuers = entra_issuers(tenant_id)
        self._audience = audience
        if signing_key is None:
            jwks = jwt.PyJWKClient(entra_jwks_url(tenant_id), cache_keys=True)
            signing_key = lambda token: jwks.get_signing_key_from_jwt(token).key  # noqa: E731
        self._signing_key = signing_key

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            key = await asyncio.to_thread(self._signing_key, token)
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuers,
                options={"require": ["exp", "iss", "aud"]},
            )
        except (jwt.PyJWTError, KeyError):
            return None
        scopes = str(claims.get("scp", "")).split()
        if REQUIRED_SCOPE not in scopes or not user_email(claims):
            return None
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("appid") or ""),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=self._audience,
            subject=str(claims.get("oid") or claims.get("sub")),
            claims=claims,
        )


def user_email(claims: dict[str, Any]) -> str | None:
    """The signed-in user's address, from whichever claim this token type carries."""
    for name in ("email", "preferred_username", "upn"):
        value = claims.get(name)
        if isinstance(value, str) and "@" in value:
            return value.lower()
    return None
