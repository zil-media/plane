# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import timedelta
from uuid import uuid4

# Django imports
from django.db import transaction
from django.utils import timezone

# Third Party imports
from botocore.exceptions import BotoCoreError, ClientError
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from plane.app.permissions import allow_permission, ROLE
from plane.app.serializers import ImportJobSerializer
from plane.bgtasks.notion_import_task import notion_import_task
from plane.db.models import ImportJob, Project, Workspace, WorkspaceMember
from plane.settings.storage import S3Storage
from plane.utils.exception_logger import log_exception
from plane.utils.importers.notion import (
    NotionExportParser,
    NotionExportError,
    NotionEntryTooLargeError,
)
from plane.utils.importers.notion.transformer import extract_people
from plane.utils.path_validator import sanitize_filename

# Module imports
from .. import BaseAPIView

# Notion exports bundle every asset — keep a generous but bounded limit
MAX_IMPORT_ZIP_SIZE = 512 * 1024 * 1024  # 512MB

# Cap the synchronous comment-author scan so a very large export can't tie up
# the request worker; authors past this budget are mapped to the importing user
# by default (and still get visible attribution) instead of blocking analyze.
AUTHOR_SCAN_BYTE_BUDGET = 64 * 1024 * 1024  # 64MB of decompressed HTML


class NotionImportJobEndpoint(BaseAPIView):
    model = ImportJob
    serializer_class = ImportJobSerializer
    parser_classes = (MultiPartParser, FormParser)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug):
        jobs = ImportJob.objects.filter(workspace__slug=slug).select_related("initiated_by")
        serializer = ImportJobSerializer(jobs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug):
        workspace = Workspace.objects.get(slug=slug)

        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            return Response({"error": "No file was uploaded."}, status=status.HTTP_400_BAD_REQUEST)
        if uploaded_file.size > MAX_IMPORT_ZIP_SIZE:
            return Response(
                {"error": "The export zip exceeds the maximum allowed size (512MB)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Analyze the export synchronously. parse() only reads entry names and
        # streams the first 4KB of each page, so it is fast; the comment-author
        # scan below reads page bodies, which is bounded by AUTHOR_SCAN_BYTE_BUDGET.
        parser = NotionExportParser(uploaded_file)
        try:
            manifest = parser.parse()
            # collect Notion comment authors and person-property names (leads,
            # assignees, …) so the wizard can map them to workspace members
            authors = set()
            scanned = 0
            truncated = False
            for page in manifest["pages"].values():
                remaining = AUTHOR_SCAN_BYTE_BUDGET - scanned
                if remaining <= 0:
                    truncated = True
                    break
                try:
                    # cap each read to the remaining budget so a single large
                    # page can't overshoot the declared scan ceiling
                    raw = parser.read_entry(page["path"], max_bytes=remaining)
                except NotionEntryTooLargeError:
                    # over budget: stop scanning (classified by type, never by
                    # message text, which embeds the attacker-controlled name)
                    truncated = True
                    break
                except NotionExportError:
                    # a single corrupt page: skip it and keep scanning the rest
                    continue
                except KeyError:
                    continue
                scanned += len(raw)
                # one parse per page yields both authors and person names
                authors |= extract_people(raw)
            manifest["comment_authors"] = sorted(authors)
            if truncated:
                manifest["comment_authors_truncated"] = True
        except NotionExportError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            parser.close()

        # Persist the export to object storage. Plane's S3Storage is a
        # presigned-URL helper, not a Django FileField backend (its __init__
        # skips super().__init__()), so assigning the upload to the FileField
        # would trigger the storage _save() path and raise. Upload the bytes
        # ourselves (server-side, no request -> internal endpoint) and store
        # only the resulting object key.
        uploaded_file.seek(0)
        safe_name = sanitize_filename(uploaded_file.name) or "export.zip"
        zip_key = f"{workspace.id}/imports/{uuid4().hex}-{safe_name[-100:]}"
        storage = S3Storage()
        try:
            stored = storage.upload_file(uploaded_file, object_name=zip_key, content_type="application/zip")
        except (BotoCoreError, ClientError) as e:
            log_exception(e)
            stored = False
        if not stored:
            return Response(
                {
                    "error": "Could not store the export in object storage. "
                    "Verify the API can reach AWS_S3_ENDPOINT_URL and that the bucket exists."
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        job = ImportJob.objects.create(
            workspace=workspace,
            initiated_by=request.user,
            source="notion",
            status=ImportJob.Status.ANALYZED,
            zip_file=zip_key,
            manifest=manifest,
        )
        serializer = ImportJobSerializer(job)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class NotionImportJobDetailEndpoint(BaseAPIView):
    model = ImportJob
    serializer_class = ImportJobSerializer

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def get(self, request, slug, pk):
        job = ImportJob.objects.select_related("initiated_by").get(workspace__slug=slug, pk=pk)
        serializer = ImportJobSerializer(job)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def delete(self, request, slug, pk):
        job = ImportJob.objects.get(workspace__slug=slug, pk=pk)
        # PROCESSING jobs older than the Celery hard limit (+ buffer) are
        # zombies (worker crash / lost dispatch) — allow cleaning those up.
        stale_cutoff = timezone.now() - timedelta(seconds=7200)
        if job.status == ImportJob.Status.PROCESSING and job.updated_at > stale_cutoff:
            return Response(
                {"error": "A running import cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if job.zip_file:
            S3Storage().delete_files([job.zip_file.name])
        job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotionImportJobRunEndpoint(BaseAPIView):
    model = ImportJob
    serializer_class = ImportJobSerializer

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, pk):
        project_id = request.data.get("project_id")
        if not project_id:
            return Response(
                {"error": "A destination project is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        project = Project.objects.filter(workspace__slug=slug, pk=project_id).first()
        if project is None:
            return Response({"error": "Project not found."}, status=status.HTTP_400_BAD_REQUEST)

        # per-database import mode: {"<database uuid>": "pages" | "work_items"}
        databases_config = request.data.get("databases", {})
        if not isinstance(databases_config, dict):
            return Response(
                {"error": "The databases configuration must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Notion comment author -> workspace member id mapping
        users_config = request.data.get("users", {})
        if not isinstance(users_config, dict):
            return Response(
                {"error": "The users configuration must be an object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lock the job row and flip it to PROCESSING atomically so a double
        # submit (or two API workers) can't both pass the status check and
        # dispatch the import twice.
        with transaction.atomic():
            job = ImportJob.objects.select_for_update().get(workspace__slug=slug, pk=pk)
            if job.status not in [ImportJob.Status.ANALYZED, ImportJob.Status.FAILED]:
                return Response(
                    {"error": "This import has already been started."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            known_databases = set(job.manifest.get("databases", {}).keys())
            invalid = [
                uuid
                for uuid, mode in databases_config.items()
                if uuid not in known_databases or mode not in ("pages", "work_items")
            ]
            if invalid:
                return Response(
                    {"error": f"Invalid database configuration: {', '.join(invalid)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if users_config:
                member_ids = set(
                    str(member_id)
                    for member_id in WorkspaceMember.objects.filter(
                        workspace__slug=slug, is_active=True, member_id__in=list(users_config.values())
                    ).values_list("member_id", flat=True)
                )
                invalid_users = [author for author, user_id in users_config.items() if str(user_id) not in member_ids]
                if invalid_users:
                    return Response(
                        {"error": f"Mapped users are not workspace members: {', '.join(invalid_users)}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            job.project = project
            job.config = {"databases": databases_config, "users": users_config}
            job.status = ImportJob.Status.PROCESSING
            job.report = {}
            job.reason = ""
            job.save()

        # Dispatch only after the PROCESSING state is committed, so the worker
        # never races ahead of the row it is about to read. A failed dispatch
        # must not leave the job stuck at PROCESSING with nothing enqueued.
        def _dispatch():
            try:
                notion_import_task.delay(job_id=str(job.id))
            except Exception as e:
                log_exception(e)
                ImportJob.objects.filter(pk=job.id, status=ImportJob.Status.PROCESSING).update(
                    status=ImportJob.Status.FAILED,
                    reason=f"dispatch_failed: {e}"[:2000],
                )

        transaction.on_commit(_dispatch)

        serializer = ImportJobSerializer(job)
        return Response(serializer.data, status=status.HTTP_200_OK)
