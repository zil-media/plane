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

from bs4 import BeautifulSoup
from celery import shared_task
from django.core.files.base import ContentFile

from plane.db.models import (
    FileAsset,
    ImportJob,
    Issue,
    IssueComment,
    IssueLabel,
    Label,
    Page,
    ProjectPage,
)
from plane.utils.content_validator import validate_html_content
from plane.utils.exception_logger import log_exception
from plane.utils.importers.notion import NotionExportParser
from plane.utils.importers.notion.transformer import (
    ASSET_SCHEME,
    PAGE_SCHEME,
    NotionHTMLTransformer,
)

EXTERNAL_SOURCE = "notion"


@shared_task
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


def _run_import(job):
    workspace = job.workspace
    project = job.project
    user = job.initiated_by
    database_modes = (job.config or {}).get("databases", {})
    # Notion comment author display name -> workspace member id
    author_mapping = (job.config or {}).get("users", {})

    with job.zip_file.open("rb") as f:
        parser = NotionExportParser(io.BytesIO(f.read()))
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
        "warnings": [],
    }

    # ------------------------------------------------------------------
    # plan: which notion pages become Plane pages vs work items
    # ------------------------------------------------------------------
    def database_mode(database_uuid):
        return database_modes.get(database_uuid, "pages")

    page_order = []  # parents before children

    def walk(uuid):
        page_order.append(uuid)
        for child in pages[uuid]["children"]:
            walk(child)
        for database_uuid, database in databases.items():
            if database["parent"] == uuid and database_mode(database_uuid) == "pages":
                for row in database["rows"]:
                    walk(row)

    for root in manifest["root_pages"]:
        walk(root)

    work_item_rows = [
        (database_uuid, row)
        for database_uuid, database in databases.items()
        if database_mode(database_uuid) == "work_items"
        for row in database["rows"]
    ]

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
    row_labels = _database_row_labels(parser, databases, database_modes)
    for database_uuid, uuid in work_item_rows:
        page = pages[uuid]
        existing = Issue.objects.filter(
            project=project, external_source=EXTERNAL_SOURCE, external_id=uuid
        ).first()
        if existing:
            existing.name = page["title"][:255]
            existing.save(created_by_id=user.id)
            plane_issues[uuid] = existing
            report["work_items_updated"] += 1
        else:
            issue = Issue(
                workspace=workspace,
                project=project,
                name=page["title"][:255],
                description_html="<p></p>",
                external_source=EXTERNAL_SOURCE,
                external_id=uuid,
            )
            issue.save(created_by_id=user.id)
            plane_issues[uuid] = issue
            report["work_items_created"] += 1
        for label_name in row_labels.get(uuid, []):
            label, _ = Label.objects.get_or_create(
                project=project,
                name=label_name,
                defaults={"workspace": workspace, "created_by_id": user.id},
            )
            IssueLabel.objects.get_or_create(
                issue=plane_issues[uuid],
                label=label,
                defaults={"project": project, "workspace": workspace},
            )

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
            external_id = hashlib.sha256(f"{uuid}:{comment['id']}:{comment['html']}".encode("utf-8")).hexdigest()
            if IssueComment.objects.filter(
                issue=issue, external_source=EXTERNAL_SOURCE, external_id=external_id
            ).exists():
                continue
            actor_id = author_mapping.get(comment["author"] or "")
            comment_html = comment["html"]
            if actor_id is None and comment["author"]:
                # keep attribution visible when the author has no mapped member
                comment_html = f"<p><strong>{comment['author']} (Notion):</strong></p>{comment_html}"
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
                target = page_url(href[len(PAGE_SCHEME):])
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

        for marker in soup.find_all("div", attrs={"data-notion-database": True}):
            database_uuid = marker["data-notion-database"]
            database = databases.get(database_uuid)
            replacement = _render_database_block(
                soup, database, database_mode(database_uuid),
                page_url, slug, project_id, pages,
            )
            if replacement is not None:
                marker.replace_with(replacement)
            else:
                marker.decompose()

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

    parser.close()
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
    existing = FileAsset.objects.filter(
        workspace=workspace, external_source=EXTERNAL_SOURCE, external_id=external_id
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
    asset.asset.save(filename, ContentFile(data), save=True)
    return asset


def _database_row_labels(parser, databases, database_modes):
    """Map database row uuid -> label names, from the export CSV Tags column."""
    labels = {}
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
        tag_field = next((f for f in reader.fieldnames or [] if f.strip().lower() in ("tags", "etiquetas")), None)
        name_field = next((f for f in reader.fieldnames or [] if f.strip().lower() in ("name", "nombre")), None)
        if not tag_field or not name_field:
            continue
        # match CSV rows to row pages by title (order-stable for duplicates)
        rows_by_title = {}
        for row_uuid in database["rows"]:
            rows_by_title.setdefault(parser.pages[row_uuid].title.strip(), []).append(row_uuid)
        for csv_row in reader:
            title = (csv_row.get(name_field) or "").strip()
            tags = [t.strip() for t in (csv_row.get(tag_field) or "").split(",") if t.strip()]
            candidates = rows_by_title.get(title)
            if candidates:
                labels[candidates.pop(0)] = tags
    return labels


def _render_database_block(soup, database, mode, page_url, slug, project_id, pages):
    """Replace the collection marker with content pointing at the imported rows."""
    if database is None:
        return None
    if mode == "work_items":
        p = soup.new_tag("p")
        a = soup.new_tag("a", href=f"/{slug}/projects/{project_id}/issues/")
        a.string = f"{database['title']} — imported as work items"
        p.append(a)
        return p
    table = soup.new_tag("table")
    header_row = soup.new_tag("tr")
    th = soup.new_tag("th")
    th_p = soup.new_tag("p")
    th_p.string = database["title"]
    th.append(th_p)
    header_row.append(th)
    table.append(header_row)
    for row_uuid in database["rows"]:
        title = (pages.get(row_uuid) or {}).get("title") or row_uuid[:8]
        url = page_url(row_uuid)
        tr = soup.new_tag("tr")
        td = soup.new_tag("td")
        td_p = soup.new_tag("p")
        if url:
            a = soup.new_tag("a", href=url)
            a.string = title
            td_p.append(a)
        else:
            td_p.string = title
        td.append(td_p)
        tr.append(td)
        table.append(tr)
    return table
