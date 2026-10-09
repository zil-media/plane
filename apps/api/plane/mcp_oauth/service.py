# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""OAuth 2.1 for the Ops MCP server (/mcp): what lets Claude or ChatGPT connect to Ops by pasting
one URL. The client discovers where to sign in, the person taps "Permitir" in Ops, and it is
connected. Spec: MCP Authorization 2025-06-18 (RFC 9728 + RFC 8414 + RFC 7591 + PKCE S256).

The access token issued here IS an APIToken: same API-key auth, same permissions as its owner,
listed with the person's API tokens and revoked by deleting it there. OAuth opens no new door; it
automates handing over an API token. On top of a manual token it adds a 24h expiry and a refresh
token. The refresh token does not rotate (rotating forces handling two concurrent refreshes, where
the second locks the client out); it dies with the grant, and revoking the token kills it too.
"""

# Python imports
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse

# Django imports
from django.conf import settings
from django.db import transaction
from django.utils import timezone

# Module imports
from plane.db.models import APIToken, McpOAuthClient, McpOAuthCode, McpOAuthGrant, McpOAuthRequest
from plane.db.models.api import generate_token

OAUTH_SCOPE = "mcp"
ACCESS_TTL = timedelta(hours=24)
CODE_TTL = timedelta(minutes=10)
REQUEST_TTL = timedelta(minutes=30)
REFRESH_PREFIX = "plane_mcpr_"
AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")


class OAuthError(Exception):
    """RFC 6749 §5.2 error. `status` is the HTTP status that goes with it."""

    def __init__(self, code, description, status=400):
        super().__init__(description)
        self.code = code
        self.description = description
        self.status = status


# ─── Addresses ───────────────────────────────────────────────────────────────


def issuer():
    return (settings.APP_BASE_URL or settings.WEB_URL or "").rstrip("/")


def resource_url():
    return f"{issuer()}/mcp"


def authorization_server_metadata():
    base = issuer()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/auth/mcp/authorize/",
        "token_endpoint": f"{base}/auth/mcp/token/",
        "registration_endpoint": f"{base}/auth/mcp/register/",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": list(AUTH_METHODS),
        "scopes_supported": [OAUTH_SCOPE],
        "authorization_response_iss_parameter_supported": True,
    }


# ─── Client registration (RFC 7591) ──────────────────────────────────────────

# Where a client may return with the code. Closed list: the cloud connectors we support, plus the
# loopback addresses desktop clients use (RFC 8252) and the editors' own schemes.
ALLOWED_HTTPS_HOSTS = {"claude.ai", "claude.com", "chatgpt.com", "chat.openai.com", "vscode.dev", "insiders.vscode.dev"}
ALLOWED_APP_SCHEMES = {"cursor", "vscode", "vscode-insiders"}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}


def is_allowed_redirect_uri(raw):
    if not isinstance(raw, str):
        return False
    url = urlparse(raw)
    if url.fragment or not url.scheme:
        return False
    if url.scheme == "https":
        return url.hostname in ALLOWED_HTTPS_HOSTS
    if url.scheme == "http":
        return url.hostname in LOOPBACK_HOSTS
    return url.scheme in ALLOWED_APP_SCHEMES


def _is_loopback(url):
    return url.scheme == "http" and url.hostname in LOOPBACK_HOSTS


def redirect_matches(registered, requested):
    """RFC 8252 §7.3: on loopback the client picks the port on every sign-in."""
    if registered == requested:
        return True
    a, b = urlparse(registered), urlparse(requested)
    if not (_is_loopback(a) and _is_loopback(b)):
        return False
    return a.hostname == b.hostname and a.path == b.path and a.query == b.query


def hash_secret(value):
    return hashlib.sha256(value.encode()).hexdigest()


def register_client(body):
    redirect_uris = body.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris or len(redirect_uris) > 10:
        raise OAuthError("invalid_redirect_uri", "redirect_uris must be a non-empty list")
    for uri in redirect_uris:
        if not is_allowed_redirect_uri(uri):
            raise OAuthError("invalid_redirect_uri", f"Redirect destination not allowed: {uri}")
    auth_method = body.get("token_endpoint_auth_method") or "none"
    if auth_method not in AUTH_METHODS:
        raise OAuthError("invalid_client_metadata", f"Unsupported token_endpoint_auth_method: {auth_method}")

    client_id = "pmc_" + secrets.token_urlsafe(16)
    client_secret = None if auth_method == "none" else "pmcs_" + secrets.token_urlsafe(32)
    client = McpOAuthClient.objects.create(
        client_id=client_id,
        client_secret_hash=hash_secret(client_secret) if client_secret else "",
        client_name=str(body.get("client_name") or "")[:100],
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=auth_method,
    )
    response = {
        "client_id": client_id,
        "client_id_issued_at": int(client.created_at.timestamp()),
        "client_name": client.client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": auth_method,
    }
    if client_secret:
        response.update({"client_secret": client_secret, "client_secret_expires_at": 0})
    return response


def authenticate_client(request, data):
    """client_id from the body or Basic; the secret by either way, whichever was declared."""
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[6:]).decode()
            sep = decoded.index(":")
            client_id, client_secret = unquote(decoded[:sep]), unquote(decoded[sep + 1 :])
        except (ValueError, UnicodeDecodeError):
            raise OAuthError("invalid_client", "Malformed Basic credentials", 401)
    if not client_id:
        raise OAuthError("invalid_client", "Missing client_id", 401)
    client = McpOAuthClient.objects.filter(client_id=client_id).first()
    if client is None:
        raise OAuthError("invalid_client", "Unknown client", 401)
    if client.client_secret_hash:
        given = hash_secret(str(client_secret)) if client_secret else ""
        if not hmac.compare_digest(given, client.client_secret_hash):
            raise OAuthError("invalid_client", "Invalid client secret", 401)
    return client


# ─── Authorization (the consent screen) ─────────────────────────────────────


def _resource_matches(resource):
    return str(resource).rstrip("/") == resource_url()


def validate_authorize_request(params):
    """Errors are shown on the Ops page instead of redirected: redirecting an error to a
    redirect_uri not validated yet is exactly what must not happen."""
    client = McpOAuthClient.objects.filter(client_id=params.get("client_id") or "").first()
    if client is None:
        raise OAuthError(
            "invalid_client", "La app que pide conectarse no está registrada. Volvé a agregar el conector."
        )
    redirect_uri = params.get("redirect_uri")
    if not redirect_uri:
        if len(client.redirect_uris) != 1:
            raise OAuthError("invalid_request", "Falta redirect_uri.")
        redirect_uri = client.redirect_uris[0]
    if not any(redirect_matches(registered, redirect_uri) for registered in client.redirect_uris):
        raise OAuthError("invalid_request", "El destino de vuelta no coincide con el registrado por la app.")
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "Sólo se soporta response_type=code.")
    if not params.get("code_challenge"):
        raise OAuthError("invalid_request", "Falta code_challenge (PKCE).")
    if (params.get("code_challenge_method") or "plain") != "S256":
        raise OAuthError("invalid_request", "Sólo se soporta PKCE con S256.")
    if params.get("resource") and not _resource_matches(params["resource"]):
        raise OAuthError("invalid_target", f"Este servidor sólo emite tokens para {resource_url()}.")
    return client, redirect_uri


def create_pending_request(params):
    client, redirect_uri = validate_authorize_request(params)
    kept = {
        key: params.get(key) or ""
        for key in ("response_type", "code_challenge", "code_challenge_method", "state", "resource", "scope")
    }
    kept.update({"client_id": client.client_id, "redirect_uri": redirect_uri})
    return McpOAuthRequest.objects.create(client=client, params=kept, expires_at=timezone.now() + REQUEST_TTL)


def get_pending_request(request_id):
    pending = (
        McpOAuthRequest.objects.select_related("client").filter(pk=request_id, expires_at__gt=timezone.now()).first()
    )
    if pending is None:
        raise OAuthError("invalid_request", "Este pedido de conexión venció. Volvé a conectar desde la app.")
    return pending


def _redirect(redirect_uri, params):
    url = urlparse(redirect_uri)
    query = dict(parse_qsl(url.query))
    query.update({key: value for key, value in params.items() if value})
    return urlunparse(url._replace(query=urlencode(query)))


def decide_authorization(user, pending, workspace, allow):
    """The person tapped Permitir or Cancelar. Returns where to send the browser."""
    params = pending.params
    client, redirect_uri = validate_authorize_request(params)
    pending.delete()
    if not allow:
        return _redirect(redirect_uri, {"error": "access_denied", "state": params.get("state"), "iss": issuer()})
    code = secrets.token_urlsafe(32)
    McpOAuthCode.objects.create(
        code_hash=hash_secret(code),
        client=client,
        user=user,
        workspace=workspace,
        redirect_uri=redirect_uri,
        code_challenge=params["code_challenge"],
        resource=params.get("resource") or "",
        expires_at=timezone.now() + CODE_TTL,
    )
    return _redirect(redirect_uri, {"code": code, "state": params.get("state"), "iss": issuer()})


# ─── /token ──────────────────────────────────────────────────────────────────


def _pkce_challenge(verifier):
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _token_response(access_token, refresh_token):
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
        "refresh_token": refresh_token,
        "scope": OAUTH_SCOPE,
    }


def connection_label(client):
    return f"{(client.client_name or 'Conector')[:45]} (conector)"


def exchange_code(client, data):
    code, verifier = data.get("code"), data.get("code_verifier")
    if not code or not verifier:
        raise OAuthError("invalid_request", "Missing code or code_verifier")
    now = timezone.now()
    # claimed on its own, before any check: two parallel redemptions give one token, and a failed
    # attempt (wrong verifier, wrong client) burns the code
    claimed = McpOAuthCode.objects.filter(
        code_hash=hash_secret(str(code)), used_at__isnull=True, expires_at__gt=now
    ).update(used_at=now)
    if not claimed:
        raise OAuthError("invalid_grant", "Invalid, expired or already used code")
    record = McpOAuthCode.objects.select_related("user", "workspace").get(code_hash=hash_secret(str(code)))
    if record.client_id != client.id:
        raise OAuthError("invalid_grant", "The code belongs to another client")
    redirect_uri = data.get("redirect_uri")
    if redirect_uri and not redirect_matches(record.redirect_uri, redirect_uri):
        raise OAuthError("invalid_grant", "redirect_uri does not match the authorization")
    if not hmac.compare_digest(_pkce_challenge(str(verifier)), record.code_challenge):
        raise OAuthError("invalid_grant", "Invalid code_verifier")
    if data.get("resource") and not _resource_matches(data["resource"]):
        raise OAuthError("invalid_target", f"This server only issues tokens for {resource_url()}")

    with transaction.atomic():
        # reconnecting the same app replaces the previous connection instead of piling them up:
        # every "Connect" registers a new client, so it is recognised by name
        label = connection_label(client)
        APIToken.objects.filter(user=record.user, label=label, mcp_oauth_grant__isnull=False, is_active=True).update(
            is_active=False
        )
        token = APIToken.objects.create(
            user=record.user,
            workspace=record.workspace,
            label=label,
            description=f"Conexión MCP por OAuth ({client.client_name or 'app'})",
            expired_at=now + ACCESS_TTL,
        )
        refresh_token = REFRESH_PREFIX + secrets.token_urlsafe(32)
        McpOAuthGrant.objects.create(client=client, api_token=token, refresh_hash=hash_secret(refresh_token))
    return _token_response(token.token, refresh_token)


def refresh_access_token(client, data):
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        raise OAuthError("invalid_request", "Missing refresh_token")
    grant = (
        McpOAuthGrant.objects.select_related("api_token").filter(refresh_hash=hash_secret(str(refresh_token))).first()
    )
    token = grant.api_token if grant else None
    if token is None or not token.is_active or token.deleted_at is not None:
        raise OAuthError("invalid_grant", "The connection was revoked or does not exist. Connect again.")
    if grant.client_id != client.id:
        raise OAuthError("invalid_grant", "The refresh token belongs to another client")
    updated = APIToken.objects.filter(pk=token.pk, is_active=True).update(
        token=generate_token(), expired_at=timezone.now() + ACCESS_TTL
    )
    # revoked between the read and the update: don't hand out a token born dead
    if not updated:
        raise OAuthError("invalid_grant", "The connection was revoked. Connect again.")
    token.refresh_from_db(fields=["token"])
    return _token_response(token.token, str(refresh_token))
