"""Runtime Community-Edition capability keys for backend pre-flight gating.

The default is the verified baseline: no CE target probed so far supports
nested pages or page collections (see the 2026-09-04 probe in CE_COMPAT.md).
When a newer CE version is probed and verified, add its capability keys to
``_VERIFIED_CAPABILITIES``. ``PLANE_CE_CAPABILITIES`` (comma-separated keys)
explicitly overrides the default for untested targets without a release.
"""

from __future__ import annotations

import os

# Gated page capabilities. The ``pages.`` prefix keeps the door open for other
# resources to join the same mechanism.
PAGES_PARENT_ID = "pages.parent_id"
PAGES_COLLECTION_ID = "pages.collection_id"

_VERIFIED_CAPABILITIES: frozenset[str] = frozenset()


def ce_capabilities() -> frozenset[str]:
    """Verified-by-default CE capability keys; ``PLANE_CE_CAPABILITIES`` overrides."""
    override = os.getenv("PLANE_CE_CAPABILITIES", "").strip()
    if override:
        return frozenset(key.strip() for key in override.split(",") if key.strip())
    return _VERIFIED_CAPABILITIES
