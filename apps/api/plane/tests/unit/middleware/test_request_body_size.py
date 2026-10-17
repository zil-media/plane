# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Unit tests for the request body size limit and its one exception: a client folder's brand file upload.

Only a multipart POST to .../zil-client/brand-files/ may be larger than FILE_SIZE_LIMIT. Every other
request, same path or not, keeps the limit: DRF parses a JSON or urlencoded body whole in memory.
"""

from unittest.mock import Mock, PropertyMock

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from plane.middleware.logger import APITokenLogMiddleware
from plane.middleware.request_body_size import (
    BRAND_FILE_REQUEST_MAX_BYTES,
    RequestBodySizeLimitMiddleware,
    is_brand_file_upload,
)

MB = 1024 * 1024
BRAND = "/api/workspaces/nike/projects/0f1e2d3c/pages/4b5a6978/zil-client/brand-files/"
MULTIPART = "multipart/form-data; boundary=BoUnDaRy"


@pytest.fixture
def small_body_limit(settings):
    settings.DATA_UPLOAD_MAX_MEMORY_SIZE = 1024


def post(path, content_type=MULTIPART, method="POST", data=b"x", declared=None):
    extra = {} if declared is None else {"CONTENT_LENGTH": str(declared)}
    return RequestFactory().generic(method, path, data, content_type, **extra)


def body_never_read():
    """Fail the test the moment the middleware reads the whole body into memory."""
    return PropertyMock(side_effect=AssertionError("request.body was read"))


@pytest.mark.unit
class TestIsBrandFileUpload:
    @pytest.mark.parametrize(
        "content_type",
        [MULTIPART, "multipart/form-data;boundary=BoUnDaRy", "Multipart/Form-Data; boundary=BoUnDaRy"],
        ids=["multipart", "no space before the boundary", "capitals"],
    )
    def test_a_multipart_post_to_the_brand_files_of_a_folder_is_one(self, content_type):
        assert is_brand_file_upload(post(BRAND, content_type)) is True

    @pytest.mark.parametrize(
        "path",
        [
            BRAND.rstrip("/"),
            BRAND + "0123456789abcdef01234569/",
            BRAND + "../",
            BRAND.replace("pages/", "pages//"),
            BRAND.replace("projects/0f1e2d3c/", ""),
            "/x" + BRAND,
            BRAND.replace("/api/", "/api/v1/"),
            BRAND.replace("zil-client/brand-files/", "zil-client/assets/"),
            BRAND.replace("brand-files", "Brand-Files"),
        ],
        ids=[
            "no trailing slash",
            "a brand file's own url",
            "under it",
            "empty segment",
            "missing segment",
            "prefixed",
            "other api version",
            "client assets",
            "other case",
        ],
    )
    def test_no_other_path_is(self, path):
        assert is_brand_file_upload(post(path)) is False

    def test_a_trailing_newline_is_not_a_trailing_slash(self):
        # a server decodes %0A into the path, and `$` would match before it
        request = post(BRAND)
        request.path_info += "\n"
        assert is_brand_file_upload(request) is False

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "GET"])
    def test_no_other_verb_is(self, method):
        assert is_brand_file_upload(post(BRAND, method=method)) is False

    @pytest.mark.parametrize(
        "content_type",
        ["application/json", "application/x-www-form-urlencoded", "text/plain", "multipart/mixed; boundary=x", ""],
    )
    def test_no_body_that_is_not_a_multipart_form_is(self, content_type):
        assert is_brand_file_upload(post(BRAND, content_type)) is False


@pytest.mark.unit
@pytest.mark.usefixtures("small_body_limit")
class TestRequestBodySizeLimitMiddleware:
    def middleware(self):
        get_response = Mock(return_value=HttpResponse(b"ok"))
        return RequestBodySizeLimitMiddleware(get_response), get_response

    def test_a_brand_upload_past_the_body_limit_goes_through_unread(self):
        middleware, get_response = self.middleware()
        request = post(BRAND, declared=BRAND_FILE_REQUEST_MAX_BYTES)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(type(request), "body", body_never_read())
            response = middleware(request)
        assert response.status_code == 200
        get_response.assert_called_once_with(request)

    def test_a_brand_upload_past_its_own_cap_is_a_413_before_the_view(self):
        middleware, get_response = self.middleware()
        response = middleware(post(BRAND, declared=BRAND_FILE_REQUEST_MAX_BYTES + 1))
        assert response.status_code == 413
        assert b"REQUEST_BODY_TOO_LARGE" in response.content
        get_response.assert_not_called()

    @pytest.mark.parametrize("content_type", ["application/json", "application/x-www-form-urlencoded", "text/plain"])
    def test_a_brand_path_body_that_is_not_a_multipart_form_keeps_the_body_limit(self, content_type):
        middleware, get_response = self.middleware()
        response = middleware(post(BRAND, content_type, data=b"x" * (2 * 1024)))
        assert response.status_code == 413
        get_response.assert_not_called()

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
    def test_a_brand_path_request_with_another_verb_keeps_the_body_limit(self, method):
        middleware, get_response = self.middleware()
        response = middleware(post(BRAND, method=method, data=b"x" * (2 * 1024)))
        assert response.status_code == 413
        get_response.assert_not_called()

    @pytest.mark.parametrize(
        "path",
        [BRAND + "0123456789abcdef01234569/", BRAND.replace("brand-files", "assets"), "/api/workspaces/"],
        ids=["a brand file's own url", "client assets", "anything else"],
    )
    def test_every_other_multipart_post_keeps_the_body_limit(self, path):
        middleware, get_response = self.middleware()
        response = middleware(post(path, data=b"x" * (2 * 1024)))
        assert response.status_code == 413
        get_response.assert_not_called()

    def test_a_body_within_the_limit_goes_through(self):
        middleware, get_response = self.middleware()
        assert middleware(post("/api/workspaces/", "application/json", data=b"{}")).status_code == 200
        get_response.assert_called_once()


@pytest.mark.unit
class TestAPITokenLogMiddlewareBrandUpload:
    def test_it_does_not_read_a_brand_upload_whole(self):
        get_response = Mock(return_value=HttpResponse(b"{}"))
        middleware = APITokenLogMiddleware(get_response)
        request = post(BRAND)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(type(request), "body", body_never_read())
            middleware(request)
        get_response.assert_called_once_with(request)

    def test_it_reads_any_other_request_on_that_path(self):
        get_response = Mock(return_value=HttpResponse(b"{}"))
        middleware = APITokenLogMiddleware(get_response)
        request = post(BRAND, "application/json", data=b"{}")
        middleware.process_request = Mock()
        middleware(request)
        assert middleware.process_request.call_args.args[2] == b"{}"
