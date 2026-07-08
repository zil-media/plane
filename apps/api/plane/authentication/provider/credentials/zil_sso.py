# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Module imports
from plane.authentication.adapter.credential import CredentialAdapter
from plane.db.models import User


class ZilSSOProvider(CredentialAdapter):
    """Trusted SSO provider for Zil Workspace.

    Unlike the email / magic-code providers there is no secret to verify here:
    the caller (ZilSSOEndpoint) has already validated the signed JWT minted by
    Zil Workspace, so the claims are trusted. This adapter only maps those
    claims onto the shape ``complete_login_or_signup`` expects and delegates
    all user creation / activation to the base ``Adapter``.
    """

    provider = "zil-sso"

    def __init__(self, request, email, claims=None, callback=None):
        super().__init__(request=request, provider=self.provider, callback=callback)
        # ``code`` is unused (no password) but the base adapter expects the
        # attribute to exist for its autoset-password branch.
        self.code = None
        self.email = email
        self.claims = claims or {}

    def set_user_data(self):
        first_name = self.claims.get("given_name") or ""
        last_name = self.claims.get("family_name") or ""

        # Fall back to splitting a single "name" claim when the identity
        # provider only sends a display name.
        if not first_name and not last_name:
            name = (self.claims.get("name") or "").strip()
            if name:
                parts = name.split(" ", 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ""

        super().set_user_data(
            {
                "email": self.email,
                "user": {
                    "avatar": self.claims.get("avatar", ""),
                    "first_name": first_name,
                    "last_name": last_name,
                    "provider_id": self.claims.get("sub", ""),
                    # Trusted federated login: never a local password, and the
                    # email is verified upstream by Zil Workspace.
                    "is_password_autoset": True,
                },
            }
        )
        return

    @staticmethod
    def user_exists(email):
        return User.objects.filter(email=email).exists()
