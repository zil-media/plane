# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""One private project per Zil brand (Marca) in each Business Unit workspace that works it.

Zil Workspace owns brands and decides who works on each one; Ops only materialises that:
`plane.utils.zil_brand_projects` applies the roster Zil pushes to
POST /api/zil/sync/brand-projects/. The brand → project mapping lives here, never in
`Project.external_id` (that one belongs to the ERP entity links).
"""

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from .base import BaseModel


class ZilBrandProject(BaseModel):
    """A project Zil manages: a brand's project, or the private "Migración" project of a workspace.

    `identifier` is the work item key prefix allocated when the project was made; it never
    changes, since it is part of every work item key (`KFC-123`). `auto_name` is the last name the
    sync gave the project: a project renamed by hand keeps its name.

    `community_managers`, `leaders`, `materials_links` and `finals_links` are Ops' own: loaded from
    the "Marca" tab, never touched by the sync.
    """

    BRAND_KIND = "brand"
    MIGRATION_KIND = "migration"
    KIND_CHOICES = ((BRAND_KIND, "Brand"), (MIGRATION_KIND, "Migration"))

    ACTIVE = "active"
    ARCHIVED = "archived"

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="zil_brand_projects")
    project = models.OneToOneField("db.Project", on_delete=models.CASCADE, related_name="zil_brand")
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=BRAND_KIND)
    zil_brand_id = models.CharField(max_length=24, blank=True, default="")
    auto_name = models.CharField(max_length=255, blank=True, default="")
    identifier = models.CharField(max_length=12, blank=True, default="")
    logo_url = models.TextField(blank=True, default="")
    color = models.CharField(max_length=16, blank=True, default="")
    status = models.CharField(max_length=16, default=ACTIVE)
    synced_at = models.DateTimeField(null=True, blank=True)
    members_synced_at = models.DateTimeField(null=True, blank=True)
    community_managers = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="zil_brands_as_cm")
    leaders = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="zil_brands_as_leader")
    # [{"name": "Fotos", "url": "https://drive.google.com/…"}], in the order people loaded them
    materials_links = models.JSONField(default=list, blank=True)
    finals_links = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Zil Brand Project"
        verbose_name_plural = "Zil Brand Projects"
        db_table = "zil_brand_projects"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "zil_brand_id"],
                condition=models.Q(deleted_at__isnull=True, kind="brand"),
                name="zil_brand_project_unique_per_workspace",
            ),
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(deleted_at__isnull=True, kind="migration"),
                name="zil_migration_project_unique_per_workspace",
            ),
        ]

    def __str__(self):
        return f"{self.zil_brand_id or self.kind} -> {self.project_id}"


class ZilBrandMember(BaseModel):
    """Who Zil wants in a brand's project, by email.

    Kept even for people who never signed in to Ops (there is no Plane user to make a member
    of yet): their first sign-in applies it.
    """

    brand_project = models.ForeignKey(ZilBrandProject, on_delete=models.CASCADE, related_name="desired_members")
    email = models.CharField(max_length=255)
    role = models.PositiveSmallIntegerField(default=15)

    class Meta:
        verbose_name = "Zil Brand Member"
        verbose_name_plural = "Zil Brand Members"
        db_table = "zil_brand_members"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["brand_project", "email"],
                condition=models.Q(deleted_at__isnull=True),
                name="zil_brand_member_unique_email",
            )
        ]
        indexes = [models.Index(fields=["email"], name="zil_brand_member_email_idx")]

    def __str__(self):
        return f"{self.email} -> {self.brand_project_id}"


class ZilBrandRoster(BaseModel):
    """The `computed_at` of the last brand roster a workspace applied (the ordering stamp).

    A workspace that has one gets its brands as projects: its clients folder is gone, and the
    old client-folders push no longer applies to it.
    """

    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="zil_brand_rosters")
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Zil Brand Roster"
        verbose_name_plural = "Zil Brand Rosters"
        db_table = "zil_brand_rosters"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(deleted_at__isnull=True),
                name="zil_brand_roster_unique_per_workspace",
            )
        ]

    def __str__(self):
        return f"{self.workspace_id} @ {self.synced_at}"
