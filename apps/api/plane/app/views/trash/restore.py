# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
from datetime import timedelta

# Django imports
from django.db import transaction

# Children are stamped by soft_delete_related_objects right after the parent, so they carry a
# slightly later deleted_at. This window decides which children went away together with the parent.
CASCADE_WINDOW_BEFORE = timedelta(seconds=2)
CASCADE_WINDOW_AFTER = timedelta(minutes=5)


def _cascade_relations(instance):
    for relation in instance._meta.get_fields():
        if not ((relation.one_to_many or relation.one_to_one) and relation.auto_created and not relation.concrete):
            continue
        on_delete = getattr(relation.on_delete, "__name__", "")
        if on_delete in ("DO_NOTHING", "SET_NULL"):
            continue
        related_model = relation.related_model
        if not hasattr(related_model, "all_objects") or not hasattr(related_model, "deleted_at"):
            continue
        yield related_model, relation.field.name


def restore_with_children(instance, visited=None):
    """Clear deleted_at on the instance and on the children deleted together with it."""
    visited = visited if visited is not None else set()
    key = (instance._meta.label, instance.pk)
    if key in visited or instance.deleted_at is None:
        return
    visited.add(key)

    deleted_at = instance.deleted_at
    lower = deleted_at - CASCADE_WINDOW_BEFORE
    upper = deleted_at + CASCADE_WINDOW_AFTER

    # The instance is cleared first so the children never point at a hidden parent.
    type(instance).all_objects.filter(pk=instance.pk).update(deleted_at=None)
    instance.deleted_at = None

    for related_model, field_name in _cascade_relations(instance):
        children = related_model.all_objects.filter(
            **{field_name: instance, "deleted_at__gte": lower, "deleted_at__lte": upper}
        )
        for child in children:
            restore_with_children(child, visited)


def restore_instance(instance):
    with transaction.atomic():
        restore_with_children(instance)
