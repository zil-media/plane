# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Third Party imports
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from plane.app.permissions import allow_permission, ROLE
from plane.app.serializers import ImportJobSerializer
from plane.bgtasks.notion_import_task import notion_import_task
from plane.db.models import ImportJob, Project, Workspace, WorkspaceMember
from plane.utils.importers.notion import NotionExportParser, NotionExportError
from plane.utils.importers.notion.transformer import extract_comment_authors

# Module imports
from .. import BaseAPIView

# Notion exports bundle every asset — keep a generous but bounded limit
MAX_IMPORT_ZIP_SIZE = 512 * 1024 * 1024  # 512MB


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

        # Analyze the export synchronously — parsing only reads entry names
        # and file headers, so it is fast even for large exports.
        parser = NotionExportParser(uploaded_file)
        try:
            manifest = parser.parse()
            # collect Notion comment authors so the wizard can map them to members
            authors = set()
            for page in manifest["pages"].values():
                try:
                    authors |= extract_comment_authors(parser.read_entry(page["path"]))
                except KeyError:
                    continue
            manifest["comment_authors"] = sorted(authors)
        except NotionExportError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        finally:
            parser.close()

        uploaded_file.seek(0)
        job = ImportJob.objects.create(
            workspace=workspace,
            initiated_by=request.user,
            source="notion",
            status=ImportJob.Status.ANALYZED,
            zip_file=uploaded_file,
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
        if job.status == ImportJob.Status.PROCESSING:
            return Response(
                {"error": "A running import cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.zip_file.delete(save=False)
        job.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class NotionImportJobRunEndpoint(BaseAPIView):
    model = ImportJob
    serializer_class = ImportJobSerializer

    @allow_permission(allowed_roles=[ROLE.ADMIN], level="WORKSPACE")
    def post(self, request, slug, pk):
        job = ImportJob.objects.get(workspace__slug=slug, pk=pk)
        if job.status not in [ImportJob.Status.ANALYZED, ImportJob.Status.FAILED]:
            return Response(
                {"error": "This import has already been started."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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

        # Notion comment author -> workspace member id mapping
        users_config = request.data.get("users", {})
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

        notion_import_task.delay(job_id=str(job.id))

        serializer = ImportJobSerializer(job)
        return Response(serializer.data, status=status.HTTP_200_OK)
