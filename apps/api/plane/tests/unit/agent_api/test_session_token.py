# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest

from plane.agent_api.session_token import SESSION_TTL_MS, is_valid_session_token, mint_session_token
from plane.utils.agent_pipeline.routines import session_credential_lines

KEY = "k" * 64
OTHER = "o" * 64


@pytest.mark.unit
class TestSessionToken:
    def test_signed_by_its_key_only(self):
        token, _ = mint_session_token(KEY)
        assert is_valid_session_token(KEY, token)
        assert not is_valid_session_token(OTHER, token)

    def test_expired_or_stretched_is_refused(self):
        old, _ = mint_session_token(KEY, now_ms=0)
        assert not is_valid_session_token(KEY, old, now_ms=SESSION_TTL_MS + 1)
        token, _ = mint_session_token(KEY)
        prefix, expires, nonce, signature = token.split(".")
        stretched = ".".join([prefix, str(int(expires) + SESSION_TTL_MS), nonce, signature])
        assert not is_valid_session_token(KEY, stretched)

    def test_an_expiry_beyond_the_ttl_was_not_minted_here(self):
        token, _ = mint_session_token(KEY, now_ms=10 * SESSION_TTL_MS)
        assert not is_valid_session_token(KEY, token, now_ms=0)

    def test_garbage_is_refused(self):
        assert not is_valid_session_token(KEY, KEY)
        assert not is_valid_session_token(KEY, None)
        assert not is_valid_session_token("", mint_session_token(KEY)[0])

    def test_the_trigger_never_carries_the_key(self):
        lines = session_credential_lines(KEY)
        assert KEY not in "\n".join(lines)
        assert is_valid_session_token(KEY, lines[0].removeprefix("AGENT_API_KEY: "))
