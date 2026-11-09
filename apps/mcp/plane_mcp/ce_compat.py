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


_TEXT_FILTERS = ("first_name", "last_name", "email", "display_name")
_EXACT_FILTERS = ("role_slug", "is_active", "is_bot")


def members_page(
    items: Iterable[Any],
    response_cls: type[T],
    item_cls: type,
    *,
    filters: dict[str, Any],
    per_page: int | None,
    cursor: str | None,
    order_by: str | None,
) -> T:
    """Filter, sort and page a bare members list the way the Cloud ``*-lite`` endpoint would.

    The CE members endpoints return every member and take no query parameters, so without this the
    tool's filters and ``per_page`` were silently ignored. Text filters are case-insensitive
    "contains", the rest exact, all combined with AND. Cursors use Plane's
    ``"{per_page}:{page}:{offset}"`` form.
    """
    rows = [it if isinstance(it, dict) else it.model_dump() for it in (items or [])]
    for field in _TEXT_FILTERS:
        wanted = filters.get(field)
        if wanted:
            rows = [r for r in rows if wanted.lower() in str(r.get(field) or "").lower()]
    for field in _EXACT_FILTERS:
        wanted = filters.get(field)
        if wanted is not None:
            rows = [r for r in rows if r.get(field) == wanted]
    if order_by:
        key = order_by.lstrip("-")
        rows.sort(key=lambda r: (r.get(key) is None, str(r.get(key) or "").lower()), reverse=order_by.startswith("-"))

    size = max(1, min(per_page or 100, 1000))
    page = 0
    if cursor:
        try:
            page = int(cursor.split(":")[1])
        except (IndexError, ValueError):
            raise ValueError(f"Invalid cursor {cursor!r}: pass a next_cursor from a previous response.") from None
    total = len(rows)
    pages = max(1, -(-total // size))
    chunk = rows[page * size : (page + 1) * size]
    has_next = (page + 1) * size < total
    return response_cls.model_validate(
        {
            "results": [item_cls.model_validate(r).model_dump() for r in chunk],
            "total_count": total,
            "count": len(chunk),
            "total_results": total,
            "total_pages": pages,
            "next_cursor": f"{size}:{page + 1}:0" if has_next else "",
            "prev_cursor": f"{size}:{page - 1}:0" if page > 0 else "",
            "next_page_results": has_next,
            "prev_page_results": page > 0,
        }
    )
