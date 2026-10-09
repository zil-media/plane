# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""OAuth 2.1 state for connecting agents (Claude, ChatGPT…) to Ops over MCP.

The access token an agent receives IS an APIToken: same auth, same permissions as its owner,
listed with the person's API tokens, and revoked by deleting it there (its grant goes with it).
"""

# Python imports
import uuid

# Django imports
from django.conf import settings
from django.db import models


class McpOAuthClient(models.Model):
    """An app registered through dynamic client registration (RFC 7591)."""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    client_id = models.CharField(max_length=64, unique=True)
    client_secret_hash = models.CharField(max_length=128, blank=True, default="")
    client_name = models.CharField(max_length=100, blank=True, default="")
    redirect_uris = models.JSONField(default=list)
    token_endpoint_auth_method = models.CharField(max_length=32, default="none")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_oauth_clients"


class McpOAuthRequest(models.Model):
    """A validated authorize request, kept while the person signs in to Ops."""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    client = models.ForeignKey(McpOAuthClient, on_delete=models.CASCADE, related_name="requests")
    params = models.JSONField(default=dict)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_oauth_requests"


class McpOAuthCode(models.Model):
    """Single-use authorization code (10 minutes, PKCE S256)."""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    code_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(McpOAuthClient, on_delete=models.CASCADE, related_name="codes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mcp_oauth_codes")
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="mcp_oauth_codes")
    redirect_uri = models.TextField()
    code_challenge = models.CharField(max_length=128)
    resource = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_oauth_codes"


class McpOAuthGrant(models.Model):
    """Links a connector's access token (an APIToken) to its non-rotating refresh token."""

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    client = models.ForeignKey(McpOAuthClient, on_delete=models.CASCADE, related_name="grants")
    api_token = models.OneToOneField("db.APIToken", on_delete=models.CASCADE, related_name="mcp_oauth_grant")
    refresh_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "mcp_oauth_grants"
