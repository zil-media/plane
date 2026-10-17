# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import re

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse

# A client folder's brand file (PDF, JPG or PNG, up to Zil's 20 MB) is the one upload allowed
# past FILE_SIZE_LIMIT. Its body is not read here: the view's multipart parser streams the file to
# disk, which DATA_UPLOAD_MAX_MEMORY_SIZE does not count, so the request gets its own cap instead,
# the file plus room for the multipart envelope. apps/proxy/Caddyfile*.ce carry the same match and cap.
# Only a multipart POST gets it: any other body (JSON, urlencoded, another verb) is parsed whole in
# memory by DRF, so it keeps FILE_SIZE_LIMIT.
BRAND_FILE_MAX_BYTES = 20 * 1024 * 1024
BRAND_FILE_REQUEST_MAX_BYTES = 21 * 1024 * 1024
BRAND_FILE_UPLOAD_PATH = re.compile(r"/api/workspaces/[^/]+/projects/[^/]+/pages/[^/]+/zil-client/brand-files/")
REQUEST_BODY_TOO_LARGE = {
    "error": "REQUEST_BODY_TOO_LARGE",
    "detail": "The size of the request body exceeds the maximum allowed size.",
}


def is_brand_file_upload(request):
    return (
        request.method == "POST"
        and request.content_type == "multipart/form-data"
        and BRAND_FILE_UPLOAD_PATH.fullmatch(request.path_info) is not None
    )


def _declared_size(request):
    try:
        return int(request.META.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        return 0


def _too_large():
    return JsonResponse(REQUEST_BODY_TOO_LARGE, status=413)


class RequestBodySizeLimitMiddleware:
    """
    Middleware to catch RequestDataTooBig exceptions and return
    413 Request Entity Too Large instead of 400 Bad Request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_brand_file_upload(request):
            if _declared_size(request) > BRAND_FILE_REQUEST_MAX_BYTES:
                return _too_large()
            return self.get_response(request)

        try:
            _ = request.body
        except RequestDataTooBig:
            return _too_large()

        # If body size is OK, continue with the request
        return self.get_response(request)
