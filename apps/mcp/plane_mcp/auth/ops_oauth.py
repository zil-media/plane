"""Zil Ops OAuth: the MCP endpoint as a protected resource of the Ops authorization server.

Ops (Django, /auth/mcp/...) runs the OAuth flow and issues the access token, which is an Ops API
token. This side only advertises Ops as the authorization server (RFC 9728) and checks each bearer
token against Ops, which also says which workspace the connection was granted for.
"""

from __future__ import annotations

import hashlib
import os
import time

import httpx
from fastmcp.server.auth import RemoteAuthProvider, TokenVerifier
from fastmcp.server.auth.auth import AccessToken
from fastmcp.utilities.logging import get_logger

from plane_mcp.ops import api_base_url

logger = get_logger(__name__)

# a verified token is trusted for this long before Ops is asked again (revocation delay)
CACHE_SECONDS = 60
_cache: dict[str, tuple[float, AccessToken]] = {}


def public_url() -> str:
    return os.getenv("OPS_PUBLIC_URL", "").rstrip("/")


class OpsTokenVerifier(TokenVerifier):
    def __init__(self, timeout_seconds: int = 10):
        super().__init__(required_scopes=[])
        self.timeout_seconds = timeout_seconds

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{api_base_url()}/api/v1/zil-mcp/whoami/", headers={"X-Api-Key": token})
        except httpx.RequestError as exc:
            logger.warning("Ops token check failed: %s", exc)
            return None
        if response.status_code != 200:
            _cache.pop(key, None)
            return None
        info = response.json()
        workspaces = info.get("workspaces") or []
        # a token issued by the OAuth flow names its workspace; a plain personal token works when
        # the person is in exactly one workspace
        workspace_slug = info.get("workspace_slug") or (workspaces[0]["slug"] if len(workspaces) == 1 else "")
        access = AccessToken(
            token=token,
            client_id=f"ops-user:{info['user']['id']}",
            scopes=["mcp"],
            expires_at=None,
            claims={
                "workspace_slug": workspace_slug,
                "user_id": info["user"]["id"],
                "email": info["user"].get("email"),
                "auth_method": "ops_oauth",
            },
        )
        _cache[key] = (time.monotonic() + CACHE_SECONDS, access)
        return access


def ops_auth_provider() -> RemoteAuthProvider:
    base = public_url()
    if not base:
        raise ValueError("OPS_PUBLIC_URL is not set (e.g. https://ops.zil.global).")
    return RemoteAuthProvider(
        token_verifier=OpsTokenVerifier(),
        authorization_servers=[base],
        base_url=base,
        scopes_supported=["mcp"],
        resource_name="Zil Ops",
    )
