"""Unit tests for the CE app-session client (no network; requests is mocked)."""

from unittest.mock import MagicMock

import pytest
import requests
from plane.errors.errors import ConfigurationError, HttpError

from plane_mcp import app_session
from plane_mcp.app_session import AppSessionClient, session_auth_available


def _resp(status=200, json_body=None, *, content=True, content_type="application/json"):
    r = MagicMock()
    r.status_code = status
    r.reason = "OK" if status < 400 else "Error"
    r.headers = {"content-type": content_type}
    r.content = b"x" if content else b""
    r.json.return_value = json_body if json_body is not None else {}
    r.text = "" if json_body is None else str(json_body)
    return r


def _client_with_fake_session(**kw):
    """Build a client whose requests.Session is a controllable mock."""
    c = AppSessionClient(base_url="https://plane.example", email="a@b.co", password="pw", **kw)
    c._s = MagicMock()
    # csrf cookie/token endpoint
    c._s.get.return_value = _resp(json_body={"csrf_token": "tok"})
    # a jar that reports a session-id after sign-in
    jar = {}
    c._s.cookies.get.side_effect = lambda k, *a: jar.get(k)
    c._s.cookies.set.side_effect = lambda k, v, *a, **kw2: jar.__setitem__(k, v)

    def _post(url, **kw2):
        if url.endswith("/sign-in/"):
            jar["session-id"] = "sess-abc"
            return _resp(status=302, content=False)
        return _resp()

    c._s.post.side_effect = _post
    return c, jar


def test_session_auth_available(monkeypatch):
    for k in ("PLANE_SESSION_EMAIL", "PLANE_SESSION_PASSWORD", "PLANE_SESSION_COOKIE"):
        monkeypatch.delenv(k, raising=False)
    assert session_auth_available() is False
    monkeypatch.setenv("PLANE_SESSION_COOKIE", "sid")
    assert session_auth_available() is True
    monkeypatch.delenv("PLANE_SESSION_COOKIE")
    monkeypatch.setenv("PLANE_SESSION_EMAIL", "a@b.co")
    assert session_auth_available() is False  # password missing
    monkeypatch.setenv("PLANE_SESSION_PASSWORD", "pw")
    assert session_auth_available() is True


def test_requires_credentials():
    with pytest.raises(ConfigurationError):
        AppSessionClient(base_url="https://x")


def test_lazy_login_then_get():
    c, _ = _client_with_fake_session()
    c._s.request.return_value = _resp(json_body={"results": []})
    assert not c._authed
    out = c.get("workspaces/w/projects/p/archived-issues/")
    assert out == {"results": []}
    assert c._authed
    # login happened: csrf fetched + sign-in posted
    c._s.get.assert_called()  # get-csrf-token
    assert any("/sign-in/" in call.args[0] for call in c._s.post.call_args_list)


def test_unsafe_method_sends_csrf_header():
    c, _ = _client_with_fake_session()
    c._s.request.return_value = _resp(status=204, content=False)
    c.post("workspaces/w/projects/p/issues/i/archive/", json={})
    method = c._s.request.call_args.args[0]
    headers = c._s.request.call_args.kwargs["headers"]
    assert method == "POST"
    assert headers["X-CSRFToken"] == "tok"
    assert headers["Referer"].startswith("https://plane.example")


def test_401_triggers_single_relogin_and_retry():
    c, _ = _client_with_fake_session()
    responses = [_resp(status=401, content=False), _resp(json_body={"ok": True})]
    c._s.request.side_effect = lambda *a, **k: responses.pop(0)
    out = c.get("workspaces/w/projects/p/pages/")
    assert out == {"ok": True}
    # two app calls total (initial + retry); login ran at least twice
    signins = [call for call in c._s.post.call_args_list if "/sign-in/" in call.args[0]]
    assert len(signins) >= 2


def test_403_get_is_not_retried_or_reauthenticated():
    c, _ = _client_with_fake_session()
    c._s.request.return_value = _resp(status=403, json_body={"detail": "forbidden"})

    with pytest.raises(HttpError) as ei:
        c.get("workspaces/w/projects/p/pages/")

    assert ei.value.status_code == 403
    assert c._s.request.call_count == 1
    signins = [call for call in c._s.post.call_args_list if "/sign-in/" in call.args[0]]
    assert len(signins) == 1


@pytest.mark.parametrize("status", [401, 403, 500])
def test_write_response_is_never_replayed(status):
    c, _ = _client_with_fake_session()
    c._s.request.return_value = _resp(status=status, json_body={"detail": "failed"})

    with pytest.raises(HttpError) as ei:
        c.post("workspaces/w/projects/p/pages/p/archive/", json={})

    assert ei.value.status_code == status
    expected = "Read the resource before retrying" if status >= 500 else "correct the request before retrying"
    assert expected in str(ei.value)
    assert c._s.request.call_count == 1
    signins = [call for call in c._s.post.call_args_list if "/sign-in/" in call.args[0]]
    assert len(signins) == 1


def test_write_transport_error_is_not_replayed():
    c, _ = _client_with_fake_session()
    c._s.request.side_effect = requests.Timeout("timed out")

    with pytest.raises(HttpError) as ei:
        c.post("workspaces/w/projects/p/pages/p/archive/", json={})

    assert ei.value.status_code == 0
    assert "may have reached Plane" in str(ei.value)
    assert c._s.request.call_count == 1


def test_read_transport_error_is_mapped():
    c, _ = _client_with_fake_session()
    c._s.request.side_effect = requests.Timeout("timed out")
    with pytest.raises(HttpError, match="Read request failed") as ei:
        c.get("workspaces/w/projects/p/pages/")
    assert ei.value.status_code == 0


def test_http_error_mapped():
    c, _ = _client_with_fake_session()
    c._s.request.return_value = _resp(status=400, json_body={"error": "bad state"})
    with pytest.raises(HttpError) as ei:
        c.post("workspaces/w/projects/p/issues/i/archive/", json={})
    assert ei.value.status_code == 400


def test_bad_password_raises_configuration_error():
    c = AppSessionClient(base_url="https://plane.example", email="a@b.co", password="wrong")
    c._s = MagicMock()
    c._s.get.return_value = _resp(json_body={"csrf_token": "tok"})
    c._s.cookies.get.return_value = None  # no session-id planted
    c._s.post.return_value = _resp(status=200)
    with pytest.raises(ConfigurationError):
        c.get("workspaces/w/projects/p/pages/")


def test_cookie_mode_skips_signin(monkeypatch):
    c = AppSessionClient(base_url="https://plane.example", session_cookie="sid-123")
    c._s = MagicMock()
    c._s.get.return_value = _resp(json_body={"csrf_token": "tok"})
    jar = {}
    c._s.cookies.set.side_effect = lambda k, v, *a, **kw: jar.__setitem__(k, v)
    c._s.request.return_value = _resp(json_body=[])
    c.get("workspaces/w/projects/p/pages/")
    # never calls sign-in in cookie mode
    assert not any("/sign-in/" in call.args[0] for call in c._s.post.call_args_list)
    assert jar["session-id"] == "sid-123"


def test_get_app_session_requires_base_url(monkeypatch):
    app_session.reset_app_session()
    monkeypatch.delenv("PLANE_BASE_URL", raising=False)
    monkeypatch.setenv("PLANE_SESSION_COOKIE", "sid")
    with pytest.raises(ConfigurationError):
        app_session.get_app_session()
    app_session.reset_app_session()
