"""Community-Edition compatibility helpers.

The official ``plane-sdk`` targets Plane **Cloud** endpoints. Several of them do
not exist on a self-hosted **Community Edition** instance and return ``404``:

* the ``*-lite`` list endpoints (``projects-lite``, ``project-members-lite``,
  ``members-lite``, and the ``lite`` variants of cycles/modules) — Cloud-only
  performance endpoints. The full endpoints (``projects``, ``project-members``,
  ``members``, ``cycles``, ``modules``) return the same data on CE.

These helpers let a tool *prefer* the Cloud endpoint but transparently fall back
to the CE-compatible one on ``404``, reshaping the fuller response into the same
paginated envelope the tool already advertises so its output schema is unchanged.

See ``CE_COMPAT.md`` for the full compatibility matrix.
"""

from collections.abc import Callable, Iterable
from typing import Any, TypeVar

from plane.errors.errors import HttpError

T = TypeVar("T")


def lite_or_fallback(lite_call: Callable[[], T], full_call: Callable[[], T]) -> T:
    """Call the Cloud ``lite_call``; on ``404`` (missing on CE) retry ``full_call``.

    Any other :class:`HttpError` (and every non-HTTP error) propagates unchanged,
    so genuine failures are not masked.
    """
    try:
        return lite_call()
    except HttpError as exc:
        if exc.status_code == 404:
            return full_call()
        raise


def reshape_paginated(
    full_response: Any,
    response_cls: type[T],
    item_cls: type,
    *,
    keep: Callable[[dict], bool] | None = None,
) -> T:
    """Reshape a full paginated response into a ``*Lite`` paginated envelope.

    Copies the pagination fields verbatim and re-validates each ``results`` item
    through the trimmed ``item_cls`` (extra fields are dropped by Pydantic).

    Args:
        full_response: a paginated response model from the full endpoint.
        response_cls: the ``Paginated*LiteResponse`` class the tool returns.
        item_cls: the trimmed item class (e.g. ``ProjectLite``).
        keep: optional predicate on each raw item dict; items returning ``False``
            are dropped (used to mirror the lite endpoint's ``include_archived=False``).
    """
    data = full_response.model_dump()
    items = data.pop("results", []) or []
    if keep is not None:
        items = [it for it in items if keep(it)]
    data["results"] = [item_cls.model_validate(it).model_dump() for it in items]
    return response_cls.model_validate(data)


def list_to_paginated(items: Iterable[Any], response_cls: type[T], item_cls: type) -> T:
    """Wrap a bare (unpaginated) list into a single-page paginated envelope.

    Used for the members endpoints, whose full variant returns ``list[Member]``
    while the tool advertises a paginated ``Paginated*MemberResponse``.
    """
    rows = [item_cls.model_validate(it if isinstance(it, dict) else it.model_dump()) for it in (items or [])]
    n = len(rows)
    return response_cls.model_validate(
        {
            "results": [r.model_dump() for r in rows],
            "total_count": n,
            "count": n,
            "total_results": n,
            "total_pages": 1,
            "next_cursor": "",
            "prev_cursor": "",
            "next_page_results": False,
            "prev_page_results": False,
        }
    )
