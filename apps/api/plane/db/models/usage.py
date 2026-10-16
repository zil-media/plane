# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import uuid

from django.conf import settings
from django.db import models


class UsageDay(models.Model):
    """How much each person used each part of Ops on a given day, per workspace.

    One row per (day, user, workspace, surface, channel), counted by
    plane.middleware.usage.UsageTrackingMiddleware from successful API requests.
    Feeds the usage metrics Zil Workspace reads (GET /api/zil/sync/metrics/).
    The workspace is stored by slug: requests carry the slug, and this keeps the
    count a single upsert with no lookup.
    """

    SURFACES = (
        "work_items",
        "intake",
        "pages",
        "client_profile",
        "cycles",
        "modules",
        "views",
        "notifications",
        "search",
        "analytics",
        "projects",
        "members",
        "support",
        "other",
    )

    id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True, primary_key=True)
    date = models.DateField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_days")
    workspace_slug = models.CharField(max_length=48)
    surface = models.CharField(max_length=32)
    # web = the Ops app (session); api = API keys (agents, MCP, integrations)
    channel = models.CharField(max_length=8, default="web")
    reads = models.PositiveIntegerField(default=0)
    writes = models.PositiveIntegerField(default=0)
    first_at = models.DateTimeField()
    last_at = models.DateTimeField()

    class Meta:
        db_table = "usage_days"
        verbose_name = "Usage Day"
        verbose_name_plural = "Usage Days"
        constraints = [
            models.UniqueConstraint(
                fields=["date", "user", "workspace_slug", "surface", "channel"], name="usage_day_unique"
            )
        ]
        indexes = [models.Index(fields=["workspace_slug", "date"], name="usage_day_ws_date_idx")]

    def __str__(self):
        return f"{self.date} {self.user_id} {self.workspace_slug} {self.surface}"
