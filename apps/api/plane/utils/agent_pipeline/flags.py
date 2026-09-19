# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from plane.db.models import AgentFeatureFlag


def is_feature_enabled(key):
    """Gate for code the feature agent builds: every entry point checks its flag, off by default."""
    return AgentFeatureFlag.objects.filter(key=key, enabled=True).exists()


def enabled_flag_keys():
    return list(AgentFeatureFlag.objects.filter(enabled=True).values_list("key", flat=True))
