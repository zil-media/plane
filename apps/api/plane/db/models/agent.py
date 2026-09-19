# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .base import BaseModel


class BugReport(BaseModel):
    """A bug filed in-app, by a browser crash, or by a server 5xx. Worked by the bug-fix agent."""

    class Status(models.TextChoices):
        OPEN = "open"
        IN_PROGRESS = "in_progress"
        # merged into agent-batch, not deployed yet
        FIXED = "fixed"
        RESOLVED = "resolved"
        DISMISSED = "dismissed"
        ARCHIVED = "archived"

    class Severity(models.TextChoices):
        BLOQUEANTE = "bloqueante"
        MOLESTO = "molesto"
        SUGERENCIA = "sugerencia"

    class Source(models.TextChoices):
        MANUAL = "manual"
        AUTO = "auto"

    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="bug_reports"
    )
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.SET_NULL, null=True, blank=True, related_name="bug_reports"
    )
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MOLESTO)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)

    # context captured with the report
    url = models.CharField(max_length=2000, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    viewport = models.JSONField(default=dict, blank=True)
    system_info = models.JSONField(default=dict, blank=True)
    console_logs = models.JSONField(default=list, blank=True)
    attachment_ids = models.JSONField(default=list, blank=True)

    # auto reports: grouped by fingerprint instead of filed once per occurrence
    origin = models.CharField(max_length=30, blank=True, default="")
    fingerprint = models.CharField(max_length=255, blank=True, default="", db_index=True)
    occurrences = models.PositiveIntegerField(default=1)
    affected_user_ids = models.JSONField(default=list, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_escalated_at = models.DateTimeField(null=True, blank=True)
    error_type = models.CharField(max_length=255, blank=True, default="")
    stack_trace = models.TextField(blank=True, default="")

    # agent workflow
    claimed_at = models.DateTimeField(null=True, blank=True)
    progress = models.JSONField(default=list, blank=True)
    # still open, but out of the agent queue until a person looks at it
    blocked_at = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.TextField(blank=True, default="")
    commit_hash = models.CharField(max_length=64, blank=True, default="")
    fixed_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="resolved_bug_reports"
    )
    admin_notes = models.TextField(blank=True, default="")
    derived_feature = models.ForeignKey(
        "db.FeatureRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="source_bugs"
    )

    # what the reporter reads: the reply and the readable card the agent rewrites
    resolved_message = models.TextField(blank=True, default="")
    display_title = models.CharField(max_length=70, blank=True, default="")
    category = models.CharField(max_length=40, blank=True, default="")
    plain_summary = models.CharField(max_length=200, blank=True, default="")
    comments = models.JSONField(default=list, blank=True)
    last_reopened_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Bug Report"
        verbose_name_plural = "Bug Reports"
        db_table = "bug_reports"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["status", "blocked_at"], name="bug_report_queue_idx")]

    def __str__(self):
        return f"{self.status} <{self.display_title or self.description[:40]}>"


class FeatureRequest(BaseModel):
    """A feature suggestion: specced by the feature agent, approved by an admin, then built dark."""

    class Status(models.TextChoices):
        SUBMITTED = "submitted"
        SPEC_RUNNING = "spec_running"
        SPEC_READY = "spec_ready"
        NEEDS_INFO = "needs_info"
        APPROVED = "approved"
        BUILDING = "building"
        # high impact: a human reviews and merges the PR
        IN_REVIEW = "in_review"
        # low/medium impact: merged into agent-batch, ships in the next window
        QUEUED = "queued"
        MERGED = "merged"
        REJECTED = "rejected"
        ON_HOLD = "on_hold"

    class Priority(models.TextChoices):
        BAJA = "baja"
        MEDIA = "media"
        ALTA = "alta"

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="feature_requests"
    )
    workspace = models.ForeignKey(
        "db.Workspace", on_delete=models.SET_NULL, null=True, blank=True, related_name="feature_requests"
    )
    # what the person typed; never overwritten
    title = models.CharField(max_length=200)
    problem = models.TextField()
    desired_outcome = models.TextField(blank=True, default="")
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIA)
    source_url = models.CharField(max_length=2000, blank=True, default="")
    attachment_ids = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED, db_index=True)

    spec = models.JSONField(default=dict, blank=True)
    spec_runs = models.PositiveIntegerField(default=0)
    spec_requested_at = models.DateTimeField(null=True, blank=True)
    approval = models.JSONField(default=dict, blank=True)
    rejection = models.JSONField(default=dict, blank=True)
    build = models.JSONField(default=dict, blank=True)
    flag_key = models.CharField(max_length=100, blank=True, default="")

    display_title = models.CharField(max_length=70, blank=True, default="")
    category = models.CharField(max_length=40, blank=True, default="")
    plain_summary = models.CharField(max_length=200, blank=True, default="")
    comments = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Feature Request"
        verbose_name_plural = "Feature Requests"
        db_table = "feature_requests"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.status} <{self.title[:40]}>"


class AgentFeatureFlag(BaseModel):
    """Everything the feature agent builds ships behind one of these, off until an admin turns it on."""

    key = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=False)
    feature = models.ForeignKey(
        "db.FeatureRequest", on_delete=models.SET_NULL, null=True, blank=True, related_name="flags"
    )
    enabled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    enabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Agent Feature Flag"
        verbose_name_plural = "Agent Feature Flags"
        db_table = "agent_feature_flags"
        ordering = ("key",)

    def __str__(self):
        return f"{self.key}={'on' if self.enabled else 'off'}"


class AgentPipelineConfig(BaseModel):
    """Singleton switches for the agent lanes, editable by instance admins without a redeploy."""

    bug_agent_enabled = models.BooleanField(default=True)
    # ships off: nothing fires, not even a spec, until an admin enables it
    feature_agent_enabled = models.BooleanField(default=False)
    max_builds_per_week = models.PositiveIntegerField(default=3)

    class Meta:
        verbose_name = "Agent Pipeline Config"
        verbose_name_plural = "Agent Pipeline Config"
        db_table = "agent_pipeline_config"

    @classmethod
    def get(cls):
        config = cls.objects.order_by("created_at").first()
        return config or cls.objects.create()
