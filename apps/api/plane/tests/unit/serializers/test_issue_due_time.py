# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from datetime import date, time
from unittest.mock import patch

import pytest
from rest_framework import serializers

from plane.app.serializers.issue import IssueCreateSerializer


FLAG_PATH = "plane.app.serializers.issue.is_feature_enabled"


@pytest.mark.unit
class TestIssueDueTimeSerializer:
    def test_time_is_dropped_while_flag_is_off(self):
        serializer = IssueCreateSerializer()
        with patch(FLAG_PATH, return_value=False):
            attrs = serializer.validate({"target_date": date(2026, 10, 20), "target_time": time(15, 30)})
        assert "target_time" not in attrs

    def test_time_is_kept_while_flag_is_on(self):
        serializer = IssueCreateSerializer()
        with patch(FLAG_PATH, return_value=True):
            attrs = serializer.validate({"target_date": date(2026, 10, 20), "target_time": time(15, 30)})
        assert attrs["target_time"] == time(15, 30)

    def test_time_without_date_is_rejected(self):
        serializer = IssueCreateSerializer()
        with patch(FLAG_PATH, return_value=True):
            with pytest.raises(serializers.ValidationError):
                serializer.validate({"target_time": time(15, 30)})
