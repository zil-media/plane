# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json

import pytest

from plane.bgtasks.page_version_task import track_page_version
from plane.db.models import Page, PageVersion


@pytest.mark.contract
class TestPageVersionTask:
    @pytest.mark.django_db
    def test_an_edit_saves_a_version_and_the_next_one_updates_it(self, workspace, create_user):
        page = Page.objects.create(
            name="Brief",
            workspace=workspace,
            owned_by=create_user,
            description_html="<p>nuevo</p>",
            description_json={"type": "doc", "content": [{"type": "paragraph"}]},
        )
        track_page_version(page.id, json.dumps({"description_html": "<p>viejo</p>"}), create_user.id)

        version = PageVersion.objects.get(page=page)
        assert version.owned_by_id == create_user.id
        assert version.description_json == page.description_json

        Page.objects.filter(pk=page.pk).update(description_html="<p>otra vez</p>", description_json={"type": "doc"})
        track_page_version(page.id, json.dumps({"description_html": "<p>nuevo</p>"}), create_user.id)
        assert PageVersion.objects.filter(page=page).count() == 1
        assert PageVersion.objects.get(page=page).description_json == {"type": "doc"}
