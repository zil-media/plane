# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Zil's service-key calls and the client panel never meet DRF's anonymous throttle.

Every Zil request comes from one IP and carries no session, so the default throttle (anon,
30/min per IP, one bucket for all of them) would answer 429 to Zil's sync of many users, its
roster push for all workspaces, the pickers of the whole team... at once. The service key is the
credential: these views are not anonymous.
"""

from unittest import mock

import pytest
from django.urls import URLPattern
from rest_framework import status
from rest_framework.test import APIClient

from plane.authentication import zil_support_urls, zil_sync_urls
from plane.authentication.views.zil_sync import ZilServiceView
from plane.db.models import PageZilClientLink

ZIL_ENV = {"ZIL_BASE_URL": "http://zil.test", "ZIL_SERVICE_SECRET": "secret"}
# more than the anon rate (30/min) in one go: what a full sync or the whole team's pickers send
BURST = 35
CLIENT_ID = "0123456789abcdef01234567"
RELAY = "plane.app.views.page.zil_client.zil_client_relay"


def service_endpoints():
    """(url name, path, verb) of every ZilServiceView mounted under /api/zil/, found in the url confs."""
    found = []
    for conf in (zil_sync_urls, zil_support_urls):
        for pattern in conf.urlpatterns:
            assert isinstance(pattern, URLPattern)
            view_class = getattr(pattern.callback, "view_class", None)
            if view_class is not None and issubclass(view_class, ZilServiceView):
                verb = "post" if hasattr(view_class, "post") else "get"
                found.append((pattern.name, f"/api/zil/{pattern.pattern}", verb))
    return found


@pytest.fixture(autouse=True)
def no_background_tasks():
    with (
        mock.patch("plane.app.views.page.base.page_transaction.delay"),
        mock.patch("plane.app.views.page.base.recent_visited_task.delay"),
        mock.patch("plane.app.views.page.base.refresh_zil_client_link.delay"),
        mock.patch.dict("os.environ", ZIL_ENV),
    ):
        yield


@pytest.mark.contract
class TestServiceKeyViewsAreNotThrottled:
    def test_every_service_view_is_found(self):
        # a url conf the helper does not read would let a throttled view through the burst test
        names = {name for name, _, _ in service_endpoints()}
        assert {"zil-sync-user", "zil-sync-client-folders", "zil-sync-metrics", "zil-sync-support-tracking"} <= names

    @pytest.mark.django_db
    @pytest.mark.parametrize("name,path,verb", service_endpoints(), ids=[name for name, _, _ in service_endpoints()])
    def test_a_burst_with_the_service_key_is_not_a_429(self, name, path, verb):
        client = APIClient()
        client.credentials(HTTP_X_ZIL_SERVICE_KEY="secret")
        # an empty request: each view answers its own 400/404/200 before touching anything
        statuses = [getattr(client, verb)(path, {}, format="json").status_code for _ in range(BURST)]
        assert status.HTTP_429_TOO_MANY_REQUESTS not in statuses, f"{name} throttled after {statuses.index(429)} calls"

    @pytest.mark.django_db
    def test_a_wrong_key_is_still_refused(self):
        client = APIClient()
        client.credentials(HTTP_X_ZIL_SERVICE_KEY="wrong")
        assert client.post("/api/zil/sync/user/", {}, format="json").status_code in (401, 403)


@pytest.mark.contract
class TestClientPanelIsNotThrottled:
    @pytest.mark.django_db
    def test_a_person_working_the_panel_is_not_a_429(self, session_client, workspace):
        # one open of the panel is one profile read plus the drive listings the person clicks; a
        # person is authenticated, so the anon throttle does not count them
        base = f"/api/workspaces/{workspace.slug}/projects/"
        project = session_client.post(base, {"name": "Panel", "identifier": "PNL"}, format="json").data
        pages = f"{base}{project['id']}/pages/"
        folder = session_client.post(pages, {"name": "Nike", "kind": "folder"}, format="json").data
        PageZilClientLink.objects.create(
            workspace=workspace, project_id=project["id"], page_id=folder["id"], zil_client_id=CLIENT_ID, alias="Nike"
        )
        with mock.patch(RELAY, return_value=(200, {"info": {}})):
            statuses = [
                session_client.get(f"{pages}{folder['id']}/zil-client/profile/").status_code for _ in range(BURST)
            ]
        assert statuses == [status.HTTP_200_OK] * BURST
