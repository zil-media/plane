# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


def base_fields():
    return [
        ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Created At")),
        ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Last Modified At")),
        ("deleted_at", models.DateTimeField(blank=True, null=True, verbose_name="Deleted At")),
        (
            "id",
            models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                primary_key=True,
                serialize=False,
                unique=True,
            ),
        ),
        (
            "created_by",
            models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_created_by",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Created By",
            ),
        ),
        (
            "updated_by",
            models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="%(class)s_updated_by",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Last Modified By",
            ),
        ),
    ]


class Migration(migrations.Migration):
    dependencies = [
        ("db", "0123_page_kind_pagezilclientlink"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeatureRequest",
            fields=[
                *base_fields(),
                ("title", models.CharField(max_length=200)),
                ("problem", models.TextField()),
                ("desired_outcome", models.TextField(blank=True, default="")),
                (
                    "priority",
                    models.CharField(
                        choices=[("baja", "Baja"), ("media", "Media"), ("alta", "Alta")],
                        default="media",
                        max_length=10,
                    ),
                ),
                ("source_url", models.CharField(blank=True, default="", max_length=2000)),
                ("attachment_ids", models.JSONField(blank=True, default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("submitted", "Submitted"),
                            ("spec_running", "Spec Running"),
                            ("spec_ready", "Spec Ready"),
                            ("needs_info", "Needs Info"),
                            ("approved", "Approved"),
                            ("building", "Building"),
                            ("in_review", "In Review"),
                            ("queued", "Queued"),
                            ("merged", "Merged"),
                            ("rejected", "Rejected"),
                            ("on_hold", "On Hold"),
                        ],
                        db_index=True,
                        default="submitted",
                        max_length=20,
                    ),
                ),
                ("spec", models.JSONField(blank=True, default=dict)),
                ("spec_runs", models.PositiveIntegerField(default=0)),
                ("spec_requested_at", models.DateTimeField(blank=True, null=True)),
                ("approval", models.JSONField(blank=True, default=dict)),
                ("rejection", models.JSONField(blank=True, default=dict)),
                ("build", models.JSONField(blank=True, default=dict)),
                ("flag_key", models.CharField(blank=True, default="", max_length=100)),
                ("display_title", models.CharField(blank=True, default="", max_length=70)),
                ("category", models.CharField(blank=True, default="", max_length=40)),
                ("plain_summary", models.CharField(blank=True, default="", max_length=200)),
                ("comments", models.JSONField(blank=True, default=list)),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feature_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="feature_requests",
                        to="db.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "Feature Request",
                "verbose_name_plural": "Feature Requests",
                "db_table": "feature_requests",
                "ordering": ("-created_at",),
            },
        ),
        migrations.CreateModel(
            name="BugReport",
            fields=[
                *base_fields(),
                ("description", models.TextField()),
                (
                    "severity",
                    models.CharField(
                        choices=[("bloqueante", "Bloqueante"), ("molesto", "Molesto"), ("sugerencia", "Sugerencia")],
                        default="molesto",
                        max_length=20,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("manual", "Manual"), ("auto", "Auto")],
                        default="manual",
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Open"),
                            ("in_progress", "In Progress"),
                            ("fixed", "Fixed"),
                            ("resolved", "Resolved"),
                            ("dismissed", "Dismissed"),
                            ("archived", "Archived"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=20,
                    ),
                ),
                ("url", models.CharField(blank=True, default="", max_length=2000)),
                ("user_agent", models.TextField(blank=True, default="")),
                ("viewport", models.JSONField(blank=True, default=dict)),
                ("system_info", models.JSONField(blank=True, default=dict)),
                ("console_logs", models.JSONField(blank=True, default=list)),
                ("attachment_ids", models.JSONField(blank=True, default=list)),
                ("origin", models.CharField(blank=True, default="", max_length=30)),
                ("fingerprint", models.CharField(blank=True, db_index=True, default="", max_length=255)),
                ("occurrences", models.PositiveIntegerField(default=1)),
                ("affected_user_ids", models.JSONField(blank=True, default=list)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("last_escalated_at", models.DateTimeField(blank=True, null=True)),
                ("error_type", models.CharField(blank=True, default="", max_length=255)),
                ("stack_trace", models.TextField(blank=True, default="")),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("progress", models.JSONField(blank=True, default=list)),
                ("blocked_at", models.DateTimeField(blank=True, null=True)),
                ("blocked_reason", models.TextField(blank=True, default="")),
                ("commit_hash", models.CharField(blank=True, default="", max_length=64)),
                ("fixed_at", models.DateTimeField(blank=True, null=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("admin_notes", models.TextField(blank=True, default="")),
                ("resolved_message", models.TextField(blank=True, default="")),
                ("display_title", models.CharField(blank=True, default="", max_length=70)),
                ("category", models.CharField(blank=True, default="", max_length=40)),
                ("plain_summary", models.CharField(blank=True, default="", max_length=200)),
                ("comments", models.JSONField(blank=True, default=list)),
                ("last_reopened_at", models.DateTimeField(blank=True, null=True)),
                (
                    "derived_feature",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="source_bugs",
                        to="db.featurerequest",
                    ),
                ),
                (
                    "reported_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bug_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "resolved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="resolved_bug_reports",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "workspace",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bug_reports",
                        to="db.workspace",
                    ),
                ),
            ],
            options={
                "verbose_name": "Bug Report",
                "verbose_name_plural": "Bug Reports",
                "db_table": "bug_reports",
                "ordering": ("-created_at",),
                "indexes": [models.Index(fields=["status", "blocked_at"], name="bug_report_queue_idx")],
            },
        ),
        migrations.CreateModel(
            name="AgentFeatureFlag",
            fields=[
                *base_fields(),
                ("key", models.CharField(max_length=100, unique=True)),
                ("enabled", models.BooleanField(default=False)),
                ("enabled_at", models.DateTimeField(blank=True, null=True)),
                (
                    "enabled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "feature",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="flags",
                        to="db.featurerequest",
                    ),
                ),
            ],
            options={
                "verbose_name": "Agent Feature Flag",
                "verbose_name_plural": "Agent Feature Flags",
                "db_table": "agent_feature_flags",
                "ordering": ("key",),
            },
        ),
        migrations.CreateModel(
            name="AgentPipelineConfig",
            fields=[
                *base_fields(),
                ("bug_agent_enabled", models.BooleanField(default=True)),
                ("feature_agent_enabled", models.BooleanField(default=False)),
                ("max_builds_per_week", models.PositiveIntegerField(default=3)),
            ],
            options={
                "verbose_name": "Agent Pipeline Config",
                "verbose_name_plural": "Agent Pipeline Config",
                "db_table": "agent_pipeline_config",
            },
        ),
    ]
