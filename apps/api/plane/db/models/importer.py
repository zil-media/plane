# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from uuid import uuid4

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .base import BaseModel
from .project import ProjectBaseModel


def get_import_upload_path(instance, filename):
    return f"{instance.workspace_id}/imports/{uuid4().hex}-{filename[-100:]}"


class ImportJob(BaseModel):
    """A third-party import (e.g. a Notion HTML export) into a project."""

    class Status(models.TextChoices):
        UPLOADED = "uploaded"
        ANALYZED = "analyzed"
        PROCESSING = "processing"
        COMPLETED = "completed"
        FAILED = "failed"

    source = models.CharField(max_length=50, choices=(("notion", "Notion"),), default="notion")
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="import_jobs")
    project = models.ForeignKey(
        "db.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="import_jobs"
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="import_jobs"
    )
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.UPLOADED)
    zip_file = models.FileField(upload_to=get_import_upload_path, max_length=800)
    # analysis output: page tree, databases, stats (see NotionExportParser.manifest)
    manifest = models.JSONField(default=dict)
    # user configuration: destination project + per-database mode
    config = models.JSONField(default=dict)
    # import result: created entities, skipped content, warnings
    report = models.JSONField(default=dict)
    reason = models.TextField(blank=True)

    class Meta:
        verbose_name = "Import Job"
        verbose_name_plural = "Import Jobs"
        db_table = "import_jobs"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.source} <{self.workspace.slug}>"


class Importer(ProjectBaseModel):
    service = models.CharField(max_length=50, choices=(("github", "GitHub"), ("jira", "Jira")))
    status = models.CharField(
        max_length=50,
        choices=(
            ("queued", "Queued"),
            ("processing", "Processing"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ),
        default="queued",
    )
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="imports")
    metadata = models.JSONField(default=dict)
    config = models.JSONField(default=dict)
    data = models.JSONField(default=dict)
    token = models.ForeignKey("db.APIToken", on_delete=models.CASCADE, related_name="importer")
    imported_data = models.JSONField(null=True)

    class Meta:
        verbose_name = "Importer"
        verbose_name_plural = "Importers"
        db_table = "importers"
        ordering = ("-created_at",)

    def __str__(self):
        """Return name of the service"""
        return f"{self.service} <{self.project.name}>"
