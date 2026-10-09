"""Session-authenticated client for the Plane **app** API (Community Edition).

Some capabilities exist on a self-hosted CE instance but are *not* served by the
public ``/api/v1`` REST API that the ``plane-sdk`` (and a personal access token)
talks to. Notably work-item **archive/unarchive** and project **pages** live only
on the internal *app* API — the same backend the web UI uses — under ``/api/…``
(no ``/v1``) and guarded by ``BaseSessionAuthentication`` (a browser session +
CSRF), which rejects a PAT with ``401``.

This module provides an opt-in bridge: when session credentials are configured it
logs in like the web app (CSRF token + ``/auth/sign-in/``), keeps the resulting
``session-id`` cookie, and exposes small ``get``/``post``/``delete`` helpers over
the app API. Failures are surfaced as the SDK's :class:`plane.errors.HttpError`
so callers handle them uniformly.

Configuration (all optional; the bridge is inert unless credentials are present):

* ``PLANE_SESSION_EMAIL`` + ``PLANE_SESSION_PASSWORD`` — log in with these.
* ``PLANE_SESSION_COOKIE`` — reuse a pre-obtained ``session-id`` value instead
  (the password then never lives in the environment).

The public host is taken from ``PLANE_BASE_URL`` (the same value the PAT uses,
minus ``/api``); the internal server-to-server URL is intentionally *not* used
here because CSRF/trusted-origin checks expect the public https origin.

See ``CE_COMPAT.md`` for the endpoint-by-endpoint evidence.
"""

from __future__ import annotations

import os
import threading
from typing import Any
from urllib.parse import urlparse

import requests
from plane.errors.errors import ConfigurationError, HttpError

# Unsafe HTTP methods that require a CSRF token on the Django app API.
_UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def is_community_edition() -> bool:
    """Whether MCP discovery should expose only CE-compatible tools.

    ``PLANE_MCP_EDITION`` accepts ``community``/``ce`` to force CE mode and
    ``cloud`` to expose the complete SDK surface.  Its default, ``auto``,
    treats a configured non-``*.plane.so`` API host as self-hosted.  Explicit
    configuration is recommended for custom Cloud domains.
    """
    edition = os.getenv("PLANE_MCP_EDITION", "auto").strip().lower()
    if edition in {"community", "ce"}:
        return True
    if edition in {"cloud", "all"}:
        return False
    if edition != "auto":
        raise ValueError("PLANE_MCP_EDITION must be one of: auto, community (or ce), cloud (or all).")

    base_url = os.getenv("PLANE_INTERNAL_BASE_URL") or os.getenv("PLANE_BASE_URL", "")
    hostname = urlparse(base_url).hostname or ""
    return bool(hostname) and not hostname.endswith(".plane.so") and hostname != "plane.so"


def session_auth_available() -> bool:
    """Whether app-session credentials are configured.

    True when either a ready-made ``PLANE_SESSION_COOKIE`` is set, or an
    email/password pair is provided.
    """
    if os.getenv("PLANE_SESSION_COOKIE", "").strip():
        return True
    return bool(os.getenv("PLANE_SESSION_EMAIL", "").strip() and os.getenv("PLANE_SESSION_PASSWORD", "").strip())


def route_via_app_session() -> bool:
    """Whether a session-capable tool should use the app API instead of the SDK.

    True only on Community Edition *and* when app-session credentials are set.
    On Cloud, these tools keep using the public ``/api/v1`` SDK path.
    """
    return is_community_edition() and session_auth_available()


class AppSessionClient:
    """Minimal session-authenticated client for the CE app API.

    Login is lazy (performed on the first request, or the first unsafe request
    when only a cookie is supplied). A GET that receives ``401`` re-authenticates
    and retries once. Mutating requests are never replayed automatically: a lost
    response may mean that Plane already applied the change.
    """

    def __init__(
        self,
        base_url: str,
        *,
        email: str | None = None,
        password: str | None = None,
        session_cookie: str | None = None,
        timeout: float | tuple[float, float] = 30.0,
    ) -> None:
        if not (session_cookie or (email and password)):
            raise ConfigurationError(
                "App-session auth requires PLANE_SESSION_COOKIE or PLANE_SESSION_EMAIL + PLANE_SESSION_PASSWORD."
            )
        self._origin = base_url.rstrip("/")
        self._api_root = f"{self._origin}/api"
        self._auth_root = f"{self._origin}/auth"
        self._email = email
        self._password = password
        self._session_cookie = session_cookie
        self._timeout = timeout
        self._s = requests.Session()
        self._csrf: str | None = None
        self._authed = False
        self._lock = threading.Lock()

    # -- authentication -------------------------------------------------------

    def _fetch_csrf(self) -> str:
        """Fetch a CSRF token (also sets the ``csrftoken`` cookie in the jar)."""
        resp = self._s.get(f"{self._auth_root}/get-csrf-token/", timeout=self._timeout)
        if resp.status_code >= 400:
            raise HttpError(f"HTTP {resp.status_code}: {resp.reason}", resp.status_code, _payload(resp))
        token = resp.json().get("csrf_token")
        if not token:
            raise ConfigurationError("Could not obtain a CSRF token from the Plane app API.")
        return token

    def _login(self) -> None:
        """Authenticate against the app API and cache the session.

        With a pre-supplied cookie we only need a CSRF token; otherwise we run
        the email/password sign-in flow and rely on the resulting ``session-id``
        cookie stored in the session jar.
        """
        self._csrf = self._fetch_csrf()

        if self._session_cookie:
            self._s.cookies.set("session-id", self._session_cookie)
        else:
            headers = {
                "X-CSRFToken": self._csrf,
                "Referer": f"{self._origin}/",
                "Origin": self._origin,
            }
            resp = self._s.post(
                f"{self._auth_root}/sign-in/",
                data={"email": self._email, "password": self._password},
                headers=headers,
                timeout=self._timeout,
            )
            # Success is a 200/302 that plants a session-id cookie; a wrong
            # password comes back without one.
            if resp.status_code >= 400 or not self._s.cookies.get("session-id"):
                raise ConfigurationError(
                    "Plane app-session sign-in failed; check PLANE_SESSION_EMAIL / "
                    "PLANE_SESSION_PASSWORD (never logged)."
                )
        self._authed = True

    def _ensure_authed(self, *, need_csrf: bool) -> None:
        if self._authed and (self._csrf or not need_csrf):
            return
        with self._lock:
            if not (self._authed and (self._csrf or not need_csrf)):
                self._login()

    # -- requests -------------------------------------------------------------

    def request(
        self,
        method: str,
        app_path: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Call ``{origin}/api/{app_path}`` with conservative retry behavior.

        ``app_path`` is relative to the app API root, e.g.
        ``workspaces/{slug}/projects/{id}/issues/{id}/archive/``.

        Only GET requests retry once, and only after a 401.  A 403 is surfaced
        unchanged because it commonly represents an authorization or CSRF error.
        POST, PUT, PATCH, and DELETE are never retried automatically; callers
        must read the resource before deciding whether a retry is safe.
        """
        method = method.upper()
        needs_csrf = method in _UNSAFE
        self._ensure_authed(need_csrf=needs_csrf)

        try:
            resp = self._send(method, app_path, json, params)
        except requests.RequestException as exc:
            if needs_csrf:
                raise HttpError(
                    "Write request may have reached Plane but received no response. Read the resource before retrying.",
                    0,
                    str(exc),
                ) from exc
            raise HttpError(f"Read request failed before reaching Plane: {exc}", 0, str(exc)) from exc

        if needs_csrf and resp.status_code >= 400:
            if resp.status_code < 500:
                message = (
                    f"HTTP {resp.status_code}: {resp.reason}. The write request was rejected and was not applied; "
                    "correct the request before retrying."
                )
            else:
                message = (
                    f"HTTP {resp.status_code}: {resp.reason}. This write request was not retried; "
                    "its outcome may be unknown. Read the resource before retrying."
                )
            raise HttpError(
                message,
                resp.status_code,
                _payload(resp),
            )

        if method == "GET" and resp.status_code == 401:
            # A read is safe to replay after re-authentication.
            self._authed = False
            self._ensure_authed(need_csrf=needs_csrf)
            try:
                resp = self._send(method, app_path, json, params)
            except requests.RequestException as exc:
                raise HttpError(f"Read request failed before reaching Plane: {exc}", 0, str(exc)) from exc
        return _handle(resp)

    def _send(self, method: str, app_path: str, json: Any | None, params: dict[str, Any] | None) -> requests.Response:
        url = f"{self._api_root}/{app_path.lstrip('/')}"
        headers = {"Referer": f"{self._origin}/", "Origin": self._origin}
        if method in _UNSAFE and self._csrf:
            headers["X-CSRFToken"] = self._csrf
        return self._s.request(method, url, json=json, params=params, headers=headers, timeout=self._timeout)

    # convenience wrappers
    def get(self, app_path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", app_path, params=params)

    def post(self, app_path: str, *, json: Any | None = None) -> Any:
        return self.request("POST", app_path, json=json)

    def patch(self, app_path: str, *, json: Any | None = None) -> Any:
        return self.request("PATCH", app_path, json=json)

    def delete(self, app_path: str, *, json: Any | None = None) -> Any:
        return self.request("DELETE", app_path, json=json)


def _payload(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _handle(resp: requests.Response) -> Any:
    """Mirror the SDK's response handling: 2xx -> data/None, else HttpError."""
    if resp.status_code == 204 or not resp.content:
        if resp.status_code >= 400:
            raise HttpError(f"HTTP {resp.status_code}: {resp.reason}", resp.status_code, None)
        return None
    if 200 <= resp.status_code < 300:
        if "application/json" in resp.headers.get("content-type", "").lower():
            return resp.json()
        return resp.text
    raise HttpError(f"HTTP {resp.status_code}: {resp.reason}", resp.status_code, _payload(resp))


# -- module-level singleton ---------------------------------------------------

_client: AppSessionClient | None = None
_client_lock = threading.Lock()


def get_app_session() -> AppSessionClient:
    """Return the process-wide app-session client, creating it on first use.

    Raises :class:`ConfigurationError` when no session credentials are set.
    The public host is read from ``PLANE_BASE_URL`` (not the internal URL).
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            base_url = os.getenv("PLANE_BASE_URL", "").strip()
            if not base_url:
                raise ConfigurationError("PLANE_BASE_URL must be set (public host) to use app-session auth.")
            _client = AppSessionClient(
                base_url=base_url,
                email=os.getenv("PLANE_SESSION_EMAIL", "").strip() or None,
                password=os.getenv("PLANE_SESSION_PASSWORD", "").strip() or None,
                session_cookie=os.getenv("PLANE_SESSION_COOKIE", "").strip() or None,
            )
    return _client


def reset_app_session() -> None:
    """Drop the cached client (used by tests)."""
    global _client
    _client = None
