# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from unittest import mock

import pytest
from rest_framework import status


@pytest.mark.contract
class TestZilVersion:
    @pytest.mark.django_db
    def test_reports_the_build_commit_only_with_the_service_key(self, api_client):
        url = "/api/zil/sync/version/"
        with mock.patch.dict("os.environ", {"ZIL_SERVICE_SECRET": "secret", "ZIL_OPS_GIT_SHA": "a" * 40}):
            assert api_client.get(url).status_code in (401, 403)
            api_client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
            response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"sha": "a" * 40, "features": ["brand-projects"]}
