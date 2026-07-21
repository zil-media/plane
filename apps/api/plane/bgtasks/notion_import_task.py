# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Celery task that imports a parsed Notion HTML export into a project.

Runs in two passes so cross-page links can be resolved:
1. transform every page and create the ``Page``/``Issue`` rows (idempotent
   via ``external_source="notion"`` + ``external_id``), uploading assets;
2. rewrite ``notion-page://`` and ``notion-asset://`` references and the
   database markers, then store the final ``description_html``.
"""

import csv as csv_module
import hashlib
import io
import mimetypes
import posixpath
import re
import shutil
import tempfile
import time
from html import escape as html_escape
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from bs4 import BeautifulSoup
from celery import shared_task
from django.db import IntegrityError

from plane.db.models import (
    FileAsset,
    ImportJob,
    Issue,
    IssueAssignee,
    IssueComment,
    IssueLabel,
    Label,
    Page,
    ProjectMember,
    ProjectPage,
    State,
    WorkspaceMember,
)
from plane.settings.storage import S3Storage
from plane.utils.content_validator import validate_html_content
from plane.utils.exception_logger import log_exception
from plane.utils.importers.notion import NotionExportParser
from plane.utils.path_validator import sanitize_filename
from plane.utils.importers.notion.transformer import (
    ASSET_SCHEME,
    PAGE_SCHEME,
    NotionHTMLTransformer,
)

EXTERNAL_SOURCE = "notion"


# Bounded so a hung/runaway import surfaces as FAILED instead of sitting in
# PROCESSING forever: SoftTimeLimitExceeded is an Exception and is caught below.
@shared_task(soft_time_limit=3600, time_limit=3900)
def notion_import_task(job_id):
    job = ImportJob.objects.select_related("workspace", "project", "initiated_by").get(pk=job_id)
    try:
        report = _run_import(job)
        job.status = ImportJob.Status.COMPLETED
        job.report = report
        job.save(update_fields=["status", "report", "updated_at"])
    except Exception as e:
        log_exception(e)
        job.status = ImportJob.Status.FAILED
        job.reason = str(e)[:2000]
        job.save(update_fields=["status", "reason", "updated_at"])
    finally:
        # the export zip is only needed during the run; drop it from storage
        # once the job reaches a terminal state so imports don't accumulate
        if job.zip_file:
            try:
                S3Storage().delete_files([job.zip_file.name])
            except Exception as e:  # cleanup must never flip a COMPLETED job
                log_exception(e)


def _run_import(job):
    # S3Storage is a presigned-URL helper, not a Django FileField backend, so
    # job.zip_file.open() would raise. Stream the object from storage into a temp
    # file (seekable, low-RAM) and hand that to the parser instead of buffering
    # the whole archive in memory. See the upload endpoint for context.
    storage = S3Storage()
    tmp = tempfile.NamedTemporaryFile(suffix=".zip")
    try:
        # a transient S3 hiccup on the initial download shouldn't fail the whole
        # import; retry with bounded backoff before giving up
        for attempt in range(3):
            try:
                body = storage.s3_client.get_object(
                    Bucket=storage.aws_storage_bucket_name, Key=job.zip_file.name
                )["Body"]
                break
            except (BotoCoreError, ClientError):
                if attempt == 2:
                    raise
                time.sleep(2**attempt)
        shutil.copyfileobj(body, tmp)
        tmp.flush()
        tmp.seek(0)
        parser = NotionExportParser(tmp)
        try:
            return _import_with_parser(job, parser)
        finally:
            parser.close()
    finally:
        tmp.close()


def _import_with_parser(job, parser):
    workspace = job.workspace
    project = job.project
    user = job.initiated_by
    database_modes = (job.config or {}).get("databases", {})
    # Notion comment author display name -> workspace member id
    author_mapping = (job.config or {}).get("users", {})

    manifest = parser.parse()

    pages = manifest["pages"]
    databases = manifest["databases"]
    known_assets = set()
    for page in pages.values():
        known_assets.update(page["assets"])

    report = {
        "pages_created": 0,
        "pages_updated": 0,
        "work_items_created": 0,
        "work_items_updated": 0,
        "comments_created": 0,
        "page_comments_skipped": 0,
        "assets_uploaded": 0,
        "states_created": 0,
        "warnings": [],
    }

    # ------------------------------------------------------------------
    # plan: which notion pages become Plane pages vs work items
    # ------------------------------------------------------------------
    def database_mode(database_uuid):
        return database_modes.get(database_uuid, "pages")

    page_order = []  # parents before children
    visited = set()

    def walk(uuid):
        if uuid in visited:
            return
        visited.add(uuid)
        page_order.append(uuid)
        for child in pages[uuid]["children"]:
            walk(child)
        for database_uuid, database in databases.items():
            if database["parent"] == uuid and database_mode(database_uuid) == "pages":
                for row in database["rows"]:
                    walk(row)

    for root in manifest["root_pages"]:
        walk(root)

    # Top-level (parentless) databases in "pages" mode are reached by no page
    # walk above — their parent is None. Seed their rows explicitly so they are
    # imported as pages instead of being silently dropped.
    for database_uuid, database in databases.items():
        if database_mode(database_uuid) != "pages":
            continue
        parent = database["parent"]
        if parent is not None and parent in pages:
            continue  # already handled when its embedding page was walked
        for row in database["rows"]:
            walk(row)

    work_item_rows = [
        (database_uuid, row)
        for database_uuid, database in databases.items()
        if database_mode(database_uuid) == "work_items"
        for row in database["rows"]
    ]

    # subpages nested under a work-item row are still imported as pages (their
    # parent row is an Issue, so they surface at the project root; the issue's
    # description keeps the link to them)
    for _, row_uuid in work_item_rows:
        for child in pages[row_uuid]["children"]:
            walk(child)

    # ------------------------------------------------------------------
    # pass 1 — transform, create entities, upload assets
    # ------------------------------------------------------------------
    transformed = {}
    for uuid in page_order + [row for _, row in work_item_rows]:
        page = pages[uuid]
        transformer = NotionHTMLTransformer(page["path"], known_assets=known_assets)
        result = transformer.transform(parser.read_entry(page["path"]))
        transformed[uuid] = result
        for warning in result.warnings:
            report["warnings"].append(f"{page['title']}: {warning}")

    plane_pages = {}  # notion uuid -> Page
    for uuid in page_order:
        page = pages[uuid]
        parent_uuid = page["parent"] or (
            databases[page["database"]]["parent"] if page["database"] else None
        )
        existing = Page.objects.filter(
            workspace=workspace, external_source=EXTERNAL_SOURCE, external_id=uuid
        ).first()
        if existing:
            existing.name = page["title"]
            existing.parent = plane_pages.get(parent_uuid)
            existing.logo_props = _logo_props(page["icon"]) or existing.logo_props
            existing.save(created_by_id=user.id)
            plane_pages[uuid] = existing
            report["pages_updated"] += 1
        else:
            plane_page = Page(
                workspace=workspace,
                name=page["title"],
                owned_by=user,
                access=0,
                parent=plane_pages.get(parent_uuid),
                logo_props=_logo_props(page["icon"]) or {},
                external_source=EXTERNAL_SOURCE,
                external_id=uuid,
            )
            plane_page.save(created_by_id=user.id)
            plane_pages[uuid] = plane_page
            report["pages_created"] += 1
        ProjectPage.objects.get_or_create(
            project=project, page=plane_pages[uuid], defaults={"workspace": workspace}
        )

    plane_issues = {}  # notion uuid -> Issue
    row_metadata = _database_row_metadata(parser, databases, database_modes)
    # match Notion Status -> project State (by name) and Priority -> Plane priority.
    # all_state_objects: the default manager hides the seeded "Triage" state,
    # which would make a Notion status named "Triage" collide on creation.
    project_states = {
        s.name.strip().lower(): s
        for s in State.all_state_objects.filter(project=project, deleted_at__isnull=True)
    }

    def row_status(row_uuid):
        # the typed header-table properties are the richest source (they keep
        # working whatever the columns are named); the CSV is the fallback.
        # Capped at 100 chars: State.slug is a SlugField(max_length=100).
        value = next(
            (p["values"][0] for p in transformed[row_uuid].properties if p["type"] == "status" and p["values"]),
            None,
        )
        return (value or row_metadata.get(row_uuid, {}).get("status") or "").strip()[:100]

    # states the importer created before can be renamed in Plane; match those
    # by external_id first so a rename doesn't spawn a duplicate on re-import
    states_by_external_id = {
        s.external_id: s
        for s in State.all_state_objects.filter(
            project=project, external_source=EXTERNAL_SOURCE, deleted_at__isnull=True
        )
        if s.external_id
    }

    # create the Notion statuses missing from the project so rows keep their
    # original column instead of collapsing into the default state
    for status_name in sorted({row_status(uuid) for _, uuid in work_item_rows} - {""}):
        if status_name.lower() in project_states:
            continue
        status_external_id = hashlib.sha256(status_name.strip().lower().encode("utf-8")).hexdigest()
        renamed = states_by_external_id.get(status_external_id)
        if renamed is not None:
            project_states[status_name.lower()] = renamed
            continue
        try:
            state = State(
                workspace=workspace,
                project=project,
                name=status_name,
                color="#60646C",
                group=_match_state_group(status_name),
                external_source=EXTERNAL_SOURCE,
                external_id=status_external_id,
            )
            state.save(created_by_id=user.id)
            report["states_created"] += 1
        except IntegrityError:
            # unique (name, project) race or a state invisible to the manager
            state = State.all_state_objects.filter(
                project=project, name__iexact=status_name, deleted_at__isnull=True
            ).first()
            if state is None:
                report["warnings"].append(f"state_create_failed:{status_name}")
                continue
        project_states[status_name.lower()] = state

    unmapped_people = set()
    low_role_skipped = set()  # (person, reason)
    workspace_roles = {}  # member id -> workspace role (cached)
    for database_uuid, uuid in work_item_rows:
        page = pages[uuid]
        meta = row_metadata.get(uuid, {})
        props = transformed[uuid].properties
        matched_state = project_states.get(row_status(uuid).lower())
        # priority: CSV column first, else a select property whose value is a
        # known priority (that select is then consumed, not shown in the table)
        matched_priority = _match_priority(meta.get("priority"))
        if not matched_priority:
            for prop in props:
                if prop["type"] == "select" and _match_priority(prop["values"][0] if prop["values"] else None):
                    matched_priority = _match_priority(prop["values"][0])
                    break
        date_prop = next((p for p in props if p["type"] == "date"), None)
        start_date = date_prop.get("start") if date_prop else None
        target_date = date_prop.get("end") if date_prop else None
        existing = Issue.objects.filter(
            project=project, external_source=EXTERNAL_SOURCE, external_id=uuid
        ).first()
        if existing:
            existing.name = page["title"][:255]
            if matched_state:
                existing.state = matched_state
            if matched_priority:
                existing.priority = matched_priority
            if start_date:
                existing.start_date = start_date
            if target_date:
                existing.target_date = target_date
            existing.save(created_by_id=user.id)
            plane_issues[uuid] = existing
            report["work_items_updated"] += 1
        else:
            issue = Issue(
                workspace=workspace,
                project=project,
                name=page["title"][:255],
                description_html="<p></p>",
                state=matched_state,  # None -> Issue.save assigns the default state
                priority=matched_priority or "none",
                start_date=start_date,
                target_date=target_date,
                external_source=EXTERNAL_SOURCE,
                external_id=uuid,
            )
            issue.save(created_by_id=user.id)
            plane_issues[uuid] = issue
            report["work_items_created"] += 1
        label_names = list(meta.get("tags", []))
        label_colors = {}  # label name -> Plane hex, from select/multi_select tags
        for p in props:
            if p["type"] == "multi_select":
                for v in p["values"]:
                    label_names.append(v)
                    if p.get("colors", {}).get(v):
                        label_colors[v] = p["colors"][v]
        seen_labels = set()
        for label_name in label_names:
            label_name = label_name[:255]
            key = label_name.strip().lower()
            if key in seen_labels:
                continue
            seen_labels.add(key)
            label = _get_or_create_label(project, workspace, user, label_name, label_colors.get(label_name))
            IssueLabel.objects.get_or_create(
                issue=plane_issues[uuid],
                label=label,
                defaults={"project": project, "workspace": workspace},
            )
        for person in {v for p in props if p["type"] == "person" for v in p["values"]}:
            member_id = author_mapping.get(person)
            if member_id is None:
                unmapped_people.add(person)
                continue
            # never elevate a workspace guest to project member: guests can't
            # be assignees (assignee validators require role >= 15)
            workspace_role = workspace_roles.get(member_id)
            if workspace_role is None:
                member_row = WorkspaceMember.objects.filter(
                    workspace=workspace, member_id=member_id, is_active=True
                ).first()
                workspace_role = member_row.role if member_row else 0
                workspace_roles[member_id] = workspace_role
            if workspace_role < 15:
                # role 0 = not an active workspace member; 5/10 = guest/viewer
                low_role_skipped.add((person, "not a workspace member" if workspace_role == 0 else "guest"))
                continue
            # assignees must be project members for Plane to list and filter
            # them — bring mapped workspace members into the project
            project_member, _ = ProjectMember.objects.get_or_create(
                project=project,
                member_id=member_id,
                defaults={"workspace": workspace, "role": 15},
            )
            if not project_member.is_active:
                project_member.is_active = True
                project_member.save()
            IssueAssignee.objects.get_or_create(
                issue=plane_issues[uuid],
                assignee_id=member_id,
                defaults={"project": project, "workspace": workspace},
            )
    for person in sorted(unmapped_people):
        report["warnings"].append(f"unmapped_person:{person} — assignee skipped")
    for person, reason in sorted(low_role_skipped):
        report["warnings"].append(f"assignee_skipped:{person} — {reason}, cannot be an assignee")

    # Notion comments: attach to work items using the author mapping; Plane
    # pages have no comment threads, so page comments are counted as skipped.
    for uuid, result in transformed.items():
        if not result.comments:
            continue
        if uuid not in plane_issues:
            report["page_comments_skipped"] += len(result.comments)
            continue
        issue = plane_issues[uuid]
        for comment in result.comments:
            # external_id keyed on identity only (not html) so an edited Notion
            # comment updates the same row instead of orphaning a duplicate
            external_id = hashlib.sha256(f"{uuid}:{comment['id']}".encode("utf-8")).hexdigest()
            actor_id = author_mapping.get(comment["author"] or "")
            comment_html = comment["html"]
            if actor_id is None and comment["author"]:
                # keep attribution visible when the author has no mapped member
                author = html_escape(comment["author"])
                comment_html = f"<p><strong>{author} (Notion):</strong></p>{comment_html}"
            # comment_html bypasses IssueCommentSerializer (and its nh3 pass),
            # so sanitize here too; the body is already escaped in the
            # transformer, so a validation failure safely keeps that string.
            is_valid, _, clean_comment = validate_html_content(comment_html)
            if is_valid and clean_comment:
                comment_html = clean_comment
            existing_comment = IssueComment.objects.filter(
                issue=issue, external_source=EXTERNAL_SOURCE, external_id=external_id
            ).first()
            if existing_comment is not None:
                if existing_comment.comment_html != comment_html:
                    existing_comment.comment_html = comment_html
                    existing_comment.save(update_fields=["comment_html"])
                continue
            IssueComment.objects.create(
                workspace=workspace,
                project=project,
                issue=issue,
                actor_id=actor_id or user.id,
                comment_html=comment_html,
                external_source=EXTERNAL_SOURCE,
                external_id=external_id,
                created_by_id=actor_id or user.id,
            )
            report["comments_created"] += 1

    # upload every referenced asset once
    uploaded_assets = {}  # zip path -> FileAsset
    for uuid, result in transformed.items():
        for asset_path in result.asset_paths:
            if asset_path in uploaded_assets:
                continue
            asset = _upload_asset(
                parser, asset_path, workspace, project, user,
                page=plane_pages.get(uuid), issue=plane_issues.get(uuid),
            )
            if asset is not None:
                uploaded_assets[asset_path] = asset
                report["assets_uploaded"] += 1
            else:
                report["warnings"].append(f"asset_upload_failed:{posixpath.basename(asset_path)}")

    # ------------------------------------------------------------------
    # pass 2 — resolve references and store final description html
    # ------------------------------------------------------------------
    slug = workspace.slug
    project_id = str(project.id)

    def page_url(notion_uuid):
        plane_page = plane_pages.get(notion_uuid)
        if plane_page is None:
            return None
        return f"/{slug}/projects/{project_id}/pages/{plane_page.id}/"

    def issue_url(notion_uuid):
        issue = plane_issues.get(notion_uuid)
        if issue is None:
            return None
        return f"/{slug}/browse/{project.identifier}-{issue.sequence_id}/"

    def entity_url(notion_uuid):
        return page_url(notion_uuid) or issue_url(notion_uuid)

    for uuid, result in transformed.items():
        soup = BeautifulSoup(result.html, "html.parser")

        for image in soup.find_all("image-component"):
            src = image.get("src", "")
            if src.startswith(ASSET_SCHEME):
                asset = uploaded_assets.get(src[len(ASSET_SCHEME):])
                if asset is not None:
                    image["src"] = str(asset.id)
                else:
                    image.decompose()

        for anchor in soup.find_all("a"):
            href = anchor.get("href", "")
            if href.startswith(PAGE_SCHEME):
                target = entity_url(href[len(PAGE_SCHEME):])
                if target:
                    anchor["href"] = target
                else:
                    anchor.unwrap()  # target not imported — keep the text
            elif href.startswith(ASSET_SCHEME):
                asset = uploaded_assets.get(href[len(ASSET_SCHEME):])
                if asset is not None:
                    anchor["href"] = f"/api/assets/v2/workspaces/{slug}/projects/{project_id}/{asset.id}/"
                else:
                    anchor.unwrap()

        rendered_databases = set()
        for marker in soup.find_all("div", attrs={"data-notion-database": True}):
            marker_uuid = marker["data-notion-database"]
            marker_rows = set(filter(None, (marker.get("data-notion-rows") or "").split(",")))
            if marker_uuid in databases:
                targets = [marker_uuid]
            else:
                # new-format collections carry the embedding page's uuid, not a
                # database id — resolve by row uuids, else by database parent
                targets = [
                    db_uuid
                    for db_uuid, db in databases.items()
                    if marker_rows and marker_rows.intersection(db["rows"])
                ] or [db_uuid for db_uuid, db in databases.items() if db["parent"] == marker_uuid]
            for db_uuid in targets:
                if db_uuid in rendered_databases:
                    continue
                rendered_databases.add(db_uuid)
                replacement = _render_database_block(
                    soup, databases[db_uuid], entity_url, pages, transformed
                )
                if replacement is not None:
                    marker.insert_before(replacement)
            marker.decompose()

        # database rows imported as pages have no fields to carry their
        # properties — keep them all visible as a table at the top. Rows
        # imported as work items map status/labels/assignees/dates natively,
        # so only the remaining property types are prepended there.
        if pages.get(uuid, {}).get("database") and result.properties:
            if uuid in plane_pages:
                extra_props = result.properties
            else:
                # a select property carrying a priority was consumed into the
                # native priority field — don't duplicate it in the table
                extra_props = [
                    p for p in result.properties
                    if p["type"] not in ("multi_select", "status", "person", "date")
                    and not (p["type"] == "select" and _match_priority(p["values"][0] if p["values"] else None))
                ]
            if extra_props:
                props_table = soup.new_tag("table")
                for prop in extra_props:
                    tr = soup.new_tag("tr")
                    for value in (prop["name"], prop["text"]):
                        td = soup.new_tag("td")
                        td_p = soup.new_tag("p")
                        td_p.string = value
                        td.append(td_p)
                        tr.append(td)
                    props_table.append(tr)
                soup.insert(0, props_table)

        final_html = str(soup).strip() or "<p></p>"
        is_valid, _, clean_html = validate_html_content(final_html)
        if is_valid and clean_html:
            final_html = clean_html

        if uuid in plane_pages:
            plane_page = plane_pages[uuid]
            plane_page.description_html = final_html
            plane_page.description_binary = None  # regenerated from html on open
            plane_page.save(created_by_id=user.id)
        elif uuid in plane_issues:
            issue = plane_issues[uuid]
            issue.description_html = final_html
            issue.save(created_by_id=user.id)

    report["warnings"] = report["warnings"][:100]
    return report


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _logo_props(icon):
    """Notion page icon -> Plane logo_props (emoji only; svg icons skipped)."""
    if not icon or icon.startswith("/") or icon.startswith("http"):
        return None
    codepoints = "-".join(f"{ord(ch):x}" for ch in icon if ord(ch) != 0xFE0F)  # skip variation selectors
    if not codepoints:
        return None
    return {
        "in_use": "emoji",
        "emoji": {
            "value": str(ord(icon[0])),
            "url": f"https://cdn.jsdelivr.net/npm/emoji-datasource-apple/img/apple/64/{codepoints}.png",
        },
    }


def _upload_asset(parser, asset_path, workspace, project, user, page=None, issue=None):
    try:
        data = parser.read_entry(asset_path)
    except KeyError:
        return None
    filename = posixpath.basename(asset_path)
    external_id = hashlib.sha256(asset_path.encode("utf-8")).hexdigest()
    # scoped by project: reusing another project's asset row would produce
    # links that 404 behind the project-scoped asset endpoint
    existing = FileAsset.objects.filter(
        workspace=workspace, project=project, external_source=EXTERNAL_SOURCE, external_id=external_id
    ).first()
    if existing:
        return existing
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    entity_type = (
        FileAsset.EntityTypeContext.PAGE_DESCRIPTION
        if page is not None
        else FileAsset.EntityTypeContext.ISSUE_DESCRIPTION
    )
    asset = FileAsset(
        workspace=workspace,
        project=project,
        user=user,
        page=page,
        issue=issue,
        entity_type=entity_type,
        attributes={"name": filename, "type": content_type, "size": len(data)},
        size=len(data),
        is_uploaded=True,
        external_source=EXTERNAL_SOURCE,
        external_id=external_id,
        created_by=user,
    )
    # Store the object key on the FileField and push the bytes through
    # S3Storage.upload_file — assigning a File to the field would hit the
    # unsupported storage _save() path (see the upload endpoint for context).
    asset_key = f"{workspace.id}/{uuid4().hex}-{sanitize_filename(filename) or uuid4().hex}"
    asset.asset = asset_key
    storage = S3Storage()
    # bounded retry: a transient S3 hiccup should not silently drop the file
    for attempt in range(3):
        if storage.upload_file(io.BytesIO(data), object_name=asset_key, content_type=content_type):
            break
        if attempt < 2:
            time.sleep(2**attempt)
    else:
        return None
    asset.save()
    return asset


# Notion priority column values (EN/ES) -> Plane Issue.priority
_PRIORITY_ALIASES = {
    "urgent": "urgent", "urgente": "urgent", "critical": "urgent", "crítica": "urgent", "critica": "urgent",
    "high": "high", "alta": "high", "alto": "high",
    "medium": "medium", "media": "medium", "medio": "medium", "normal": "medium",
    "low": "low", "baja": "low", "bajo": "low",
    "none": "none", "ninguna": "none", "sin prioridad": "none", "no priority": "none",
}


def _match_priority(value):
    """Map a Notion priority cell to a Plane priority, or None when unknown."""
    return _PRIORITY_ALIASES.get((value or "").strip().lower())


# keyword -> Plane state group, used when creating states for Notion statuses
# (EN/ES). Checked in order; first substring hit wins, default "unstarted".
_STATE_GROUP_KEYWORDS = (
    ("cancelled", ("cancel", "cancelado", "cancelada", "cancelados", "canceladas", "cancelled", "suspendido", "suspendida", "suspendidos", "suspendidas", "pausado", "pausados", "descartado", "descartados", "abandonado", "abandonados")),
    ("completed", ("done", "complete", "completed", "completado", "completada", "completados", "completadas", "terminado", "terminada", "terminados", "finalizado", "finalizada", "finalizados", "hecho", "hechos", "entrega", "entregas", "entregado", "entregados", "delivered", "shipped", "cerrado", "cerrados")),
    ("started", ("progress", "progreso", "curso", "doing", "correcciones", "revision", "revisión", "review", "desarrollo", "haciendo")),
    ("backlog", ("backlog", "idea", "ideas")),
)
# multi-word phrases matched as substrings (word-token match can't see these)
_STATE_GROUP_PHRASES = (
    ("cancelled", ("on hold",)),
    ("started", ("en curso", "in progress")),
)


def _get_or_create_label(project, workspace, user, name, color=None):
    """Get an existing project label (case-insensitively) or create one,
    applying the Notion tag color on creation."""
    existing = Label.objects.filter(project=project, name__iexact=name).first()
    if existing is not None:
        return existing
    defaults = {"workspace": workspace, "created_by_id": user.id}
    if color:
        defaults["color"] = color
    label, _ = Label.objects.get_or_create(project=project, name=name, defaults=defaults)
    return label


def _match_state_group(name):
    lowered = name.strip().lower()
    for group, phrases in _STATE_GROUP_PHRASES:
        if any(phrase in lowered for phrase in phrases):
            return group
    tokens = set(re.split(r"[^0-9a-záéíóúñü]+", lowered))
    for group, keywords in _STATE_GROUP_KEYWORDS:
        if tokens.intersection(keywords):
            return group
    return "unstarted"


def _database_row_metadata(parser, databases, database_modes):
    """Per work-item row uuid -> {"tags": [...], "status": str, "priority": str},
    read from the export CSV (Tags / Status / Priority columns, EN or ES)."""
    metadata = {}
    for database_uuid, database in databases.items():
        if database_modes.get(database_uuid, "pages") != "work_items":
            continue
        path = database.get("csv_all_path") or database.get("csv_path")
        if not path:
            continue
        try:
            raw = parser.read_entry(path).decode("utf-8-sig", errors="replace")
        except KeyError:
            continue
        reader = csv_module.DictReader(io.StringIO(raw))
        fields = reader.fieldnames or []

        def field(*names):
            return next((f for f in fields if f.strip().lower() in names), None)

        name_field = field("name", "nombre")
        if not name_field and fields:
            # the title property is user-named ("Cliente", "Tarea", …) but
            # Notion always exports it as the first CSV column
            name_field = fields[0]
        if not name_field:
            continue
        tag_field = field("tags", "etiquetas")
        status_field = field("status", "estado")
        priority_field = field("priority", "prioridad")
        # match CSV rows to row pages by title (order-stable for duplicates)
        rows_by_title = {}
        for row_uuid in database["rows"]:
            rows_by_title.setdefault(parser.pages[row_uuid].title.strip(), []).append(row_uuid)
        for csv_row in reader:
            title = (csv_row.get(name_field) or "").strip()
            candidates = rows_by_title.get(title)
            if not candidates:
                continue
            metadata[candidates.pop(0)] = {
                "tags": [t.strip() for t in (csv_row.get(tag_field) or "").split(",") if t.strip()]
                if tag_field
                else [],
                "status": (csv_row.get(status_field) or "").strip() if status_field else "",
                "priority": (csv_row.get(priority_field) or "").strip() if priority_field else "",
            }
    return metadata


def _render_database_block(soup, database, entity_url, pages, transformed):
    """Replace the collection marker with a table linking every imported row
    (pages and work items alike), keeping the database's property columns so
    the summary reads like the source grid rather than a bare link list."""
    if database is None:
        return None

    def cell(text, href=None):
        td = soup.new_tag("td")
        td_p = soup.new_tag("p")
        if href:
            a = soup.new_tag("a", href=href)
            a.string = text
            td_p.append(a)
        else:
            td_p.string = text
        td.append(td_p)
        return td

    # property columns beyond the title, capped so wide databases stay readable
    columns = [c for c in database.get("columns", []) if c][1:5]
    table = soup.new_tag("table")
    header_row = soup.new_tag("tr")
    for header in [database["title"]] + columns:
        th = soup.new_tag("th")
        th_p = soup.new_tag("p")
        th_p.string = header
        th.append(th_p)
        header_row.append(th)
    table.append(header_row)

    for row_uuid in database["rows"]:
        title = (pages.get(row_uuid) or {}).get("title") or row_uuid[:8]
        props_by_name = {p["name"]: p["text"] for p in transformed.get(row_uuid).properties} if transformed.get(row_uuid) else {}
        tr = soup.new_tag("tr")
        tr.append(cell(title, entity_url(row_uuid)))
        for column in columns:
            tr.append(cell(props_by_name.get(column, "")))
        table.append(tr)
    return table
