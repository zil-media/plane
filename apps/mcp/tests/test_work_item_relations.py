"""Unit tests for CE work-item relation response parsing."""

import pytest
from pydantic import ValidationError

from plane_mcp.tools.work_item_relations import parse_work_item_relations


def test_parse_ce_blocked_by_objects():
    payload = {
        "blocking": [],
        "blocked_by": [
            {
                "project_id": "proj-1",
                "issue_id": "issue-1",
            }
        ],
        "duplicate": [],
        "relates_to": [],
        "start_after": [],
        "start_before": [],
        "finish_after": [],
        "finish_before": [],
    }

    parsed = parse_work_item_relations(payload)

    assert parsed.blocked_by[0].issue_id == "issue-1"
    assert parsed.blocked_by[0].project_id == "proj-1"
    assert parsed.blocking == []


def test_parse_cloud_style_uuid_strings():
    payload = {
        "blocking": ["issue-a"],
        "blocked_by": [],
        "duplicate": [],
        "relates_to": ["issue-b"],
        "start_after": [],
        "start_before": [],
        "finish_after": [],
        "finish_before": [],
    }

    parsed = parse_work_item_relations(payload)

    assert parsed.blocking[0].issue_id == "issue-a"
    assert parsed.blocking[0].project_id is None
    assert parsed.relates_to[0].issue_id == "issue-b"


def test_parse_accepts_id_alias():
    payload = {
        "blocking": [{"id": "issue-x", "project_id": "proj-x"}],
        "blocked_by": [],
        "duplicate": [],
        "relates_to": [],
        "start_after": [],
        "start_before": [],
        "finish_after": [],
        "finish_before": [],
    }

    parsed = parse_work_item_relations(payload)

    assert parsed.blocking[0].issue_id == "issue-x"


def test_parse_rejects_object_without_id():
    payload = {
        "blocking": [{"project_id": "proj-1"}],
        "blocked_by": [],
        "duplicate": [],
        "relates_to": [],
        "start_after": [],
        "start_before": [],
        "finish_after": [],
        "finish_before": [],
    }

    with pytest.raises(ValidationError):
        parse_work_item_relations(payload)
