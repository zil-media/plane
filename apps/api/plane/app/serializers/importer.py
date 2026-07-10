# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Module imports
from .base import BaseSerializer
from .user import UserLiteSerializer
from .project import ProjectLiteSerializer
from .workspace import WorkspaceLiteSerializer
from plane.db.models import Importer, ImportJob


class ImporterSerializer(BaseSerializer):
    initiated_by_detail = UserLiteSerializer(source="initiated_by", read_only=True)
    project_detail = ProjectLiteSerializer(source="project", read_only=True)
    workspace_detail = WorkspaceLiteSerializer(source="workspace", read_only=True)

    class Meta:
        model = Importer
        fields = "__all__"


class ImportJobSerializer(BaseSerializer):
    initiated_by_detail = UserLiteSerializer(source="initiated_by", read_only=True)

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "created_at",
            "updated_at",
            "source",
            "workspace",
            "project",
            "status",
            "manifest",
            "config",
            "report",
            "reason",
            "initiated_by",
            "initiated_by_detail",
        ]
        read_only_fields = fields
