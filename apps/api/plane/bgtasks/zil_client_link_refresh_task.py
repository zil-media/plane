# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third party imports
from celery import shared_task

# Django imports
from django.utils import timezone

# Module imports
from plane.db.models import PageZilClientLink
from plane.utils.exception_logger import log_exception
from plane.utils.zil_client import (
    ZilUnavailable,
    apply_zil_client_fields,
    get_zil_client,
    zil_enabled,
)


@shared_task
def refresh_zil_client_link(link_id):
    """Refresh the cached display fields of a folder's Zil client link."""
    if not zil_enabled():
        return
    link = PageZilClientLink.objects.filter(pk=link_id).select_related("workspace").first()
    if link is None:
        return
    try:
        client = get_zil_client(link.workspace.slug, link.zil_client_id)
    except ZilUnavailable:
        return
    except Exception as e:
        log_exception(e)
        return

    if client is None:
        # the client was removed or moved to another BU in Zil: keep the link, flag it
        link.lifecycle_status = "missing"
        link.synced_at = timezone.now()
    else:
        apply_zil_client_fields(link, client)
    link.save(update_fields=["alias", "company_name", "lifecycle_status", "business_unit_slug", "synced_at", "updated_at"])
