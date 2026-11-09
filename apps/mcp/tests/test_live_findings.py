"""Fixes for what a live run of every tool against Zil Ops turned up (2026-11-09)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from plane_mcp import ops
from plane_mcp.tools.cycles import _has_ended

PUBLIC = "https://ops.example.com"


@pytest.fixture()
def community(monkeypatch):
    monkeypatch.setenv("PLANE_MCP_EDITION", "community")
    monkeypatch.setenv("PLANE_API_KEY", "plane_api_k")
    monkeypatch.setenv("PLANE_WORKSPACE_SLUG", "zil")
    monkeypatch.setenv("PLANE_INTERNAL_BASE_URL", "http://api:8000")
    for var in ("PLANE_SESSION_EMAIL", "PLANE_SESSION_PASSWORD", "PLANE_SESSION_COOKIE"):
        monkeypatch.delenv(var, raising=False)


def call(tool: str, args: dict):
    from plane_mcp.server import get_stdio_mcp

    async def go():
        async with Client(get_stdio_mcp()) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(go())


class TestCommunityEditionSurface:
    def test_custom_properties_and_pql_reference_are_hidden(self, community):
        from plane_mcp.server import get_stdio_mcp

        names = {tool.name for tool in asyncio.run(get_stdio_mcp().list_tools())}
        assert not names & {"list_work_item_properties", "create_work_item_property", "get_pql_reference"}

    @pytest.mark.parametrize(
        ("tool", "args"),
        [
            ("list_cycle_work_items", {"project_id": "p", "cycle_id": "c", "pql": 'priority = "low"'}),
            ("list_module_work_items", {"project_id": "p", "module_id": "m", "pql": 'priority = "low"'}),
        ],
    )
    def test_pql_is_refused_instead_of_silently_ignored(self, community, tool, args):
        with mock.patch("plane.api.base_resource.BaseResource._get") as get:
            with pytest.raises(ToolError, match="PQL filters aren't available"):
                call(tool, args)
        assert not get.called

    def test_intake_triage_uses_the_plain_patch(self, community):
        with (
            # the call itself is what matters; stop there instead of faking a full IntakeWorkItem
            mock.patch("plane.api.intake.Intake.update", side_effect=RuntimeError("patched")) as update,
            mock.patch("plane.api.intake.Intake.update_status") as update_status,
            pytest.raises(ToolError, match="patched"),
        ):
            call("update_intake_work_item", {"project_id": "p", "work_item_id": "w", "status": 1})
        assert update.called and not update_status.called
        assert update.call_args.kwargs["data"].status == 1


class TestCycleEnded:
    def test_a_cycle_completed_today_counts_as_ended(self):
        midnight = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
        assert _has_ended(midnight)

    def test_a_cycle_ending_later_today_or_in_the_future_has_not(self):
        later = datetime.now(timezone.utc) + timedelta(hours=2)
        assert not _has_ended(later.isoformat())
        assert not _has_ended((datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat())

    def test_archive_does_not_edit_an_already_ended_cycle(self, community):
        ended = SimpleNamespace(end_date=datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z"))
        with (
            mock.patch("plane.api.cycles.Cycles.retrieve", return_value=ended),
            mock.patch("plane.api.cycles.Cycles.update") as update,
            mock.patch("plane.api.cycles.Cycles.archive", return_value=True) as archive,
        ):
            call("manage_cycle_archive", {"project_id": "p", "cycle_id": "c", "archive": True})
        assert not update.called and archive.called


class TestAttachmentsBehindTheProxy:
    @pytest.fixture()
    def public(self, monkeypatch):
        monkeypatch.setenv("OPS_PUBLIC_URL", PUBLIC)
        monkeypatch.delenv("OPS_STORAGE_INTERNAL_URL", raising=False)

    def test_sdk_calls_carry_the_public_origin(self, public):
        assert ops.public_origin_headers() == {"Host": "ops.example.com", "X-Forwarded-Proto": "https"}

    def test_presigned_urls_go_to_the_object_store_with_the_signed_host(self, public):
        url, headers = ops.internal_storage_target(f"{PUBLIC}/uploads/ws/file.txt?X-Amz-Signature=abc")
        assert url == "http://plane-minio:9000/uploads/ws/file.txt?X-Amz-Signature=abc"
        assert headers == {"Host": "ops.example.com"}

    def test_other_urls_are_left_alone(self, public):
        source = "https://raw.githubusercontent.com/a/b/main/file.txt"
        assert ops.internal_storage_target(source) == (source, {})

    def test_the_internal_address_is_configurable(self, public, monkeypatch):
        monkeypatch.setenv("OPS_STORAGE_INTERNAL_URL", "http://minio.local:9000/")
        url, _ = ops.internal_storage_target(f"{PUBLIC}/uploads/x")
        assert url == "http://minio.local:9000/uploads/x"

    def test_upload_posts_inside(self, public):
        with mock.patch.object(ops.requests, "post") as post:
            ops.storage_requests.post(f"{PUBLIC}/uploads", data={"key": "k"}, timeout=5)
        assert post.call_args.args[0] == "http://plane-minio:9000/uploads"
        assert post.call_args.kwargs["headers"] == {"Host": "ops.example.com"}
        assert post.call_args.kwargs["data"] == {"key": "k"}
