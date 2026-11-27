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

    What Ops itself keeps on the brand (CMs, líderes, Drive links) is in `ZilBrandOps`, one per
    brand and shared by every workspace that works it.
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


class ZilBrandOps(BaseModel):
    """What Ops keeps on a brand, loaded from the "Marca" tab and never touched by the sync.

    One per Zil brand, not per workspace: a brand worked by several Business Units (Meraki, Zil,
    Marketwise) shows the same CMs and Drive links in each of their workspaces. Each unit's
    Responsable is its own (`ZilBrandResponsible`).
    """

    zil_brand_id = models.CharField(max_length=24)
    community_managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="zil_brand_ops_as_cm"
    )
    # [{"name": "Fotos", "url": "https://drive.google.com/…"}], in the order people loaded them
    materials_links = models.JSONField(default=list, blank=True)
    finals_links = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Zil Brand Ops"
        verbose_name_plural = "Zil Brand Ops"
        db_table = "zil_brand_ops"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["zil_brand_id"],
                condition=models.Q(deleted_at__isnull=True),
                name="zil_brand_ops_unique_brand",
            )
        ]

    def __str__(self):
        return self.zil_brand_id


class ZilBrandResponsible(BaseModel):
    """Who answers for a brand in one Business Unit (workspace): one Responsable per unit.

    Loaded from the "Marca" tab and never touched by the sync, like `ZilBrandOps`.
    """

    zil_brand_id = models.CharField(max_length=24)
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="zil_brand_responsibles")
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="zil_brand_responsible_of"
    )

    class Meta:
        verbose_name = "Zil Brand Responsible"
        verbose_name_plural = "Zil Brand Responsibles"
        db_table = "zil_brand_responsibles"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["zil_brand_id", "workspace"],
                condition=models.Q(deleted_at__isnull=True),
                name="zil_brand_responsible_unique_unit",
            )
        ]

    def __str__(self):
        return f"{self.zil_brand_id} @ {self.workspace_id}"


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


class ZilBrandClient(BaseModel):
    """A client contact of a brand: sees that brand's portal in this workspace, nothing of Ops.

    Zil pushes them in the brand roster with `role: "client"`. A client is never a project or
    workspace member, so the team's Ops stays closed to them whatever URL they open. `user` is their
    Ops account (made by the sync when they had none); it stays empty only for a deactivated one.
    """

    brand_project = models.ForeignKey(ZilBrandProject, on_delete=models.CASCADE, related_name="clients")
    email = models.CharField(max_length=255)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="zil_brand_client_of"
    )
    # the portal invitation (plane.utils.zil_client_portal): sha256 of the single-use link's token,
    # emptied once used; a new invitation replaces the old one
    invite_token_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    invited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Zil Brand Client"
        verbose_name_plural = "Zil Brand Clients"
        db_table = "zil_brand_clients"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["brand_project", "email"],
                condition=models.Q(deleted_at__isnull=True),
                name="zil_brand_client_unique_email",
            )
        ]
        indexes = [models.Index(fields=["email"], name="zil_brand_client_email_idx")]

    def __str__(self):
        return f"{self.email} -> {self.brand_project_id} (client)"


class ZilClientPortal(BaseModel):
    """A brand project's client portal: its calendar and its "Cliente" pages folder, for its clients.

    Off until the team turns it on in the "Marca" tab. While the brand is archived (suspended or
    dropped in Zil) its clients are paused, whatever `enabled` says.
    """

    project = models.OneToOneField("db.Project", on_delete=models.CASCADE, related_name="zil_client_portal")
    enabled = models.BooleanField(default=False)
    pages_folder = models.ForeignKey(
        "db.Page", on_delete=models.SET_NULL, null=True, blank=True, related_name="zil_client_portals"
    )

    class Meta:
        verbose_name = "Zil Client Portal"
        verbose_name_plural = "Zil Client Portals"
        db_table = "zil_client_portals"
        ordering = ("-created_at",)

    def __str__(self):
        return f"portal {self.project_id} ({'on' if self.enabled else 'off'})"


class ZilPageComment(BaseModel):
    """A comment on a page of a brand's "Cliente" folder: the client and the team talk about a document.

    Every one is seen by the brand's clients (the folder is what the portal shows), like an external
    comment on a work item. Plane has no page comments; these exist only for the client portal.
    """

    page = models.ForeignKey("db.Page", on_delete=models.CASCADE, related_name="zil_client_comments")
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, related_name="zil_page_comments")
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="zil_page_comments")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="zil_page_comments")
    comment_html = models.TextField(blank=True, default="<p></p>")
    comment_stripped = models.TextField(blank=True, default="")
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Zil Page Comment"
        verbose_name_plural = "Zil Page Comments"
        db_table = "zil_page_comments"
        ordering = ("created_at",)
        indexes = [models.Index(fields=["page", "created_at"], name="zil_page_comment_page_idx")]

    def save(self, *args, **kwargs):
        from django.utils.html import strip_tags

        self.comment_stripped = strip_tags(self.comment_html or "").strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"comment on {self.page_id} by {self.actor_id}"


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
