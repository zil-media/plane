# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Session credential for a routine run.

The trigger text is kept in every run log on claude.ai, so a lane's fixed key cannot travel in
it: anyone reading a log would keep the key forever. What travels instead is a token signed with
the lane key (HMAC) that expires on its own. The key cannot be recovered from it, and it opens
only the routes of that key (each lane signs with its own) until it expires.

Stateless: verifying is signing again with the key from the environment, so there is no table to
clean, and rotating the key invalidates every live token.

Format: ``ags1.<expiry epoch-ms>.<hex nonce>.<hex signature>``.
"""

# Python imports
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone

# A routine session lasts hours (a feature build, a batch of bugs); one day covers it whole.
SESSION_TTL_MS = 24 * 60 * 60 * 1000

PREFIX = "ags1"
_SHAPE = re.compile(r"^ags1\.(\d{1,15})\.([0-9a-f]{32})\.([0-9a-f]{64})$")


def _sign(key, expires_at, nonce):
    return hmac.new(key.encode(), f"{PREFIX}.{expires_at}.{nonce}".encode(), hashlib.sha256).hexdigest()


def _now_ms():
    return int(time.time() * 1000)


def mint_session_token(key, now_ms=None):
    """Returns (token, expires_at datetime) for the lane key."""
    expires_at = (now_ms if now_ms is not None else _now_ms()) + SESSION_TTL_MS
    nonce = secrets.token_hex(16)
    token = f"{PREFIX}.{expires_at}.{nonce}.{_sign(key, expires_at, nonce)}"
    return token, datetime.fromtimestamp(expires_at / 1000, tz=timezone.utc)


def is_valid_session_token(key, token, now_ms=None):
    """True only when this key signed the token and it has not expired."""
    if not key or not isinstance(token, str):
        return False
    match = _SHAPE.match(token)
    if not match:
        return False
    raw_expires, nonce, signature = match.groups()
    expires_at = int(raw_expires)
    if expires_at <= (now_ms if now_ms is not None else _now_ms()):
        return False
    return hmac.compare_digest(signature, _sign(key, expires_at, nonce))
