# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from celery import shared_task

# Module imports
from plane.db.models import Workspace
from plane.utils.zil_client import ZilUnavailable, get_zil_client_roster, zil_enabled
from plane.utils.zil_client_folders import apply_client_folders


@shared_task
def sync_zil_client_folders(workspace_slug):
    """Pull the workspace's client roster from Zil and apply it (right after a clients root is set).

    When Zil can't be reached the folders arrive with Zil's next push (cron ops-client-folders).
    """
    if not zil_enabled():
        return None
    workspace = Workspace.objects.filter(slug=workspace_slug).first()
    if workspace is None:
        return None
    try:
        clients = get_zil_client_roster(workspace_slug)
    except ZilUnavailable:
        return None
    return apply_client_folders(workspace.id, clients, authoritative=True)
