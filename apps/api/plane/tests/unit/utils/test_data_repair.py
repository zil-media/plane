# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.apps import apps

import pytest

from plane.db.models import BugReport
from plane.utils.agent_pipeline.bugs import fingerprint_for
from plane.utils.agent_pipeline.data_repair import data_repair


@pytest.mark.unit
class TestDataRepair:
    @pytest.mark.django_db
    def test_applies_the_repair(self):
        bug = BugReport.objects.create(description="antes", source=BugReport.Source.AUTO)

        def repair(apps_):
            return apps_.get_model("db", "BugReport").objects.filter(pk=bug.pk).update(description="después")

        data_repair("ok_repair", repair)(apps, None)
        bug.refresh_from_db()
        assert bug.description == "después"

    @pytest.mark.django_db
    def test_a_failing_repair_is_undone_and_filed_without_raising(self):
        bug = BugReport.objects.create(description="antes", source=BugReport.Source.AUTO)

        def repair(apps_):
            apps_.get_model("db", "BugReport").objects.filter(pk=bug.pk).update(description="a medias")
            raise ValueError("dato inesperado")

        # Never raises: the API runs migrate on start and would not come up.
        data_repair("broken_repair", repair)(apps, None)

        bug.refresh_from_db()
        assert bug.description == "antes"
        incident = BugReport.objects.get(fingerprint=fingerprint_for("pipeline:data-repair:broken_repair"))
        assert incident.description.startswith("Incidente de pipeline: data-repair")
        assert "dato inesperado" in incident.description
        assert incident.severity == BugReport.Severity.BLOQUEANTE
        assert incident.status == BugReport.Status.OPEN
