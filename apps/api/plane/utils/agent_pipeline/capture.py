# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging
import traceback

# Django imports
from django.conf import settings

logger = logging.getLogger("plane.exception")


def _capture_enabled():
    return getattr(settings, "AGENT_CAPTURE_SERVER_ERRORS", False)


def _top_app_frame(exc):
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    for frame in reversed(frames):
        path = frame.filename.replace("\\", "/")
        if "/plane/" in path and "/site-packages/" not in path:
            return f"{path.split('/plane/', 1)[1]}:{frame.name}"
    return f"{frames[-1].name}" if frames else ""


def capture_server_error(exc, request=None):
    """Files (or bumps) an auto bug report for an unexpected 5xx. Never raises.

    Filing happens in a Celery task: the request's own transaction may be the thing that
    just broke, and the response must not wait on it.
    """
    if not _capture_enabled():
        return
    try:
        route = ""
        method = ""
        user_id = None
        workspace_slug = ""
        if request is not None:
            method = request.method
            match = getattr(request, "resolver_match", None)
            route = match.route if match else request.path
            workspace_slug = (match.kwargs.get("slug") if match else "") or ""
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated:
                user_id = str(user.id)

        where = _top_app_frame(exc)
        error_type = type(exc).__name__
        message = str(exc)[:500]
        payload = {
            "key": f"server:{error_type}:{where}:{route}",
            "description": f"{error_type}: {message}\n\n{method} /{route}".strip(),
            "error_type": error_type,
            "url": f"/{route}" if route else "",
            "stack_trace": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-20000:],
            "user_id": user_id,
            "workspace_slug": workspace_slug,
        }

        from plane.bgtasks.agent_pipeline_task import file_server_error_task

        file_server_error_task.delay(payload)
    except Exception as e:  # noqa: BLE001 — error capture must never take the request down with it
        logger.warning("server error capture failed: %s", e)


class ServerErrorCaptureMiddleware:
    """Catches exceptions that escape the views (non-DRF views, or DRF views outside BaseAPIView)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        capture_server_error(exception, request)
        return None
