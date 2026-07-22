# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Django email backend that relays outbound mail through Zil Workspace's existing
email service (Gmail API + Domain-Wide Delegation) instead of SMTP.

Plane builds every email with `get_connection(host=..., port=..., ...)`, which
instantiates `settings.EMAIL_BACKEND` and passes it the SMTP kwargs. This
backend accepts and ignores those kwargs and instead POSTs each message to Zil's
`/api/sso/mail` endpoint (authenticated with the shared service key), so Ops
notifications go out through the same pipeline / sender / domain as Zil's own
mail — no separate SMTP credentials required.

Enable by setting:
    EMAIL_BACKEND=plane.settings.zil_email_backend.ZilEmailBackend
    ZIL_BASE_URL / ZIL_SERVICE_SECRET   (already used by the sync integration)
    EMAIL_HOST=<any non-empty value>    (satisfies Plane's "email configured" gates)
"""

import os
import logging

import requests
from django.core.mail import BadHeaderError
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger("plane")


def _forbid_multi_line_header(name, value):
    """Reject header values containing \\r or \\n.

    Mirrors Django's own forbid_multi_line_headers contract (see
    django.core.mail.message), which this backend bypasses entirely since it
    builds a JSON payload for Zil's /api/sso/mail instead of going through
    Django's SafeMIMEText/EmailMessage header assembly.
    """
    val = str(value or "")
    if "\n" in val or "\r" in val:
        raise BadHeaderError("Header values can't contain newlines (got %r for header %r)" % (val, name))


class ZilEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        # Absorb and ignore the SMTP kwargs (host/port/username/password/
        # use_tls/use_ssl) that get_connection forwards.
        super().__init__(fail_silently=fail_silently)
        self.base_url = os.environ.get("ZIL_BASE_URL")
        self.secret = os.environ.get("ZIL_SERVICE_SECRET")

    def _extract_html(self, message):
        # Prefer the text/html alternative; fall back to the plain body.
        for content, mimetype in getattr(message, "alternatives", None) or []:
            if mimetype == "text/html":
                return content
        return None

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if not self.base_url or not self.secret:
            logger.warning("ZilEmailBackend not configured (ZIL_BASE_URL / ZIL_SERVICE_SECRET missing)")
            if not self.fail_silently:
                raise RuntimeError("ZilEmailBackend is not configured")
            return 0

        url = f"{self.base_url.rstrip('/')}/api/sso/mail"
        headers = {"X-Zil-Service-Key": self.secret}
        sent = 0
        first_error = None

        for message in email_messages:
            _forbid_multi_line_header("subject", message.subject)
            _forbid_multi_line_header("from", message.from_email)

            html = self._extract_html(message)
            recipients = list(message.to or [])
            if not recipients:
                continue

            ok = True
            for recipient in recipients:
                _forbid_multi_line_header("to", recipient)
                payload = {
                    "to": recipient,
                    "subject": message.subject,
                    "html": html or message.body,
                    "text": message.body,
                    "from_email": message.from_email,
                }
                # Best-effort per recipient: a failure for one must not skip the
                # rest. We record the first error and (if not fail_silently)
                # re-raise it once, after every recipient has been attempted.
                try:
                    resp = requests.post(url, json=payload, headers=headers, timeout=10)
                    if not resp.ok:
                        ok = False
                        logger.warning("ZilEmailBackend relay non-2xx: %s %s", resp.status_code, resp.text[:200])
                        if first_error is None:
                            first_error = RuntimeError(f"relay HTTP {resp.status_code}")
                except Exception as e:
                    ok = False
                    logger.warning("ZilEmailBackend relay failed: %s", e)
                    if first_error is None:
                        first_error = e
            if ok:
                sent += 1

        if first_error is not None and not self.fail_silently:
            raise first_error

        return sent
