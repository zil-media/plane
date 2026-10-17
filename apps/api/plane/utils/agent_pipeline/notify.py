# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Emails the pipeline sends, all in the "Zil Support" voice and in Spanish."""

# Django imports
from django.conf import settings

# Module imports
from plane.license.models import Instance, InstanceAdmin


def admin_users():
    instance = Instance.objects.first()
    return [
        admin.user
        for admin in InstanceAdmin.objects.filter(instance=instance, role__gte=15, user__is_active=True)
        .select_related("user")
        .order_by("user__email")
    ]


def door(user, workspace):
    """The workspace a link should go through for this person: the item's own when they are in it,
    else one of theirs (the support board is instance-wide). A link to a workspace they're not in
    answers "Workspace not found", and one with no workspace opens the app home."""
    from plane.db.models import WorkspaceMember

    memberships = WorkspaceMember.objects.filter(member=user, is_active=True, deleted_at__isnull=True)
    if workspace is not None and memberships.filter(workspace=workspace).exists():
        return workspace
    first = memberships.select_related("workspace").order_by("created_at").first()
    return first.workspace if first else None


def support_url(workspace=None, item_id=None, kind="bug"):
    base = (settings.WEB_URL or "").rstrip("/")
    if workspace is None:
        return base
    url = f"{base}/{workspace.slug}/support"
    return f"{url}?{kind}={item_id}" if item_id else url


def send(to, subject, heading, paragraphs, cta_label=None, cta_url=None):
    recipients = [e for e in (to if isinstance(to, (list, tuple)) else [to]) if e]
    if not recipients:
        return
    from plane.bgtasks.agent_pipeline_task import send_support_email_task

    send_support_email_task.delay(recipients, subject, heading, list(paragraphs), cta_label, cta_url)


def send_admins(subject, heading, paragraphs, cta_label, workspace, item_id, kind="bug"):
    """One email per admin, each with a link that opens for them (see door)."""
    for admin in admin_users():
        send(admin.email, subject, heading, paragraphs, cta_label, support_url(door(admin, workspace), item_id, kind))


def first_name(user):
    if user is None:
        return ""
    name = (user.first_name or user.display_name or "").strip()
    return name.split()[0] if name else ""


def greeting(user):
    name = first_name(user)
    return f"Hola {name}," if name else "Hola,"


def bug_resolved(bug):
    if bug.source != bug.Source.MANUAL or bug.reported_by is None:
        return
    send(
        bug.reported_by.email,
        "Resolvimos lo que reportaste",
        "Resolvimos lo que reportaste",
        [
            greeting(bug.reported_by),
            bug.resolved_message or "Ya quedó corregido el problema que nos contaste.",
            "Si vuelve a pasar, respondé desde tu seguimiento y lo miramos de nuevo.",
        ],
        "Ver mi seguimiento",
        support_url(door(bug.reported_by, bug.workspace), bug.id),
    )


def bug_user_guidance(bug):
    if bug.reported_by is None:
        return
    send(
        bug.reported_by.email,
        "Sobre lo que nos consultaste",
        "Sobre lo que nos consultaste",
        [greeting(bug.reported_by), bug.resolved_message],
        "Ver mi seguimiento",
        support_url(door(bug.reported_by, bug.workspace), bug.id),
    )


def bug_derived_to_feature(bug):
    if bug.reported_by is None or not bug.resolved_message:
        return
    send(
        bug.reported_by.email,
        "Tu pedido pasó a Sugerencias",
        "Tu pedido pasó a Sugerencias",
        [greeting(bug.reported_by), bug.resolved_message],
        "Ver mi seguimiento",
        support_url(door(bug.reported_by, bug.workspace), bug.derived_feature_id, "feature"),
    )


def bug_derived_to_workspace(bug):
    if bug.reported_by is None or not bug.resolved_message:
        return
    send(
        bug.reported_by.email,
        "Lo que reportaste lo seguimos en Zil Workspace",
        "Lo que reportaste lo seguimos en Zil Workspace",
        [greeting(bug.reported_by), bug.resolved_message],
        "Ver el seguimiento",
        bug.workspace_bug_url or support_url(door(bug.reported_by, bug.workspace), bug.id),
    )


def admins_new_bug(bug):
    who = bug.reported_by.email if bug.reported_by else "sin usuario"
    send_admins(
        f"Nuevo reporte de problema ({bug.severity})",
        "Entró un reporte nuevo",
        [f"De: {who}", f"Pantalla: {bug.url or '—'}", bug.description[:1500]],
        "Abrir la bandeja",
        bug.workspace,
        bug.id,
    )


def admins_bug_blocked(bug):
    send_admins(
        "Un arreglo automático necesita una persona",
        "El agente no puede seguir solo",
        [
            f"Reporte: {bug.display_title or bug.description[:200]}",
            f"Motivo: {bug.blocked_reason or '—'}",
            "El reporte salió de la cola del agente hasta que alguien lo revise.",
        ],
        "Abrir la bandeja",
        bug.workspace,
        bug.id,
    )


def admins_feature_build_blocked(feature, note):
    send_admins(
        "Un desarrollo automático necesita una persona",
        "El agente no puede seguir solo",
        [
            f"Sugerencia: {feature.display_title or feature.title}",
            f"Motivo: {note or 'sin detalle'}",
            "Mientras tanto, el carril de desarrollo sigue con la próxima sugerencia aprobada.",
        ],
        "Abrir la sugerencia",
        feature.workspace,
        feature.id,
        "feature",
    )


def admins_new_feature(feature):
    who = feature.requested_by.email if feature.requested_by else "—"
    send_admins(
        "Nueva sugerencia",
        "Entró una sugerencia nueva",
        [f"De: {who}", feature.title, feature.problem[:1500]],
        "Ver sugerencias",
        feature.workspace,
        feature.id,
        "feature",
    )


def admins_feature_needs_decision(feature):
    send_admins(
        "Una sugerencia espera tu decisión",
        "Hay un análisis listo para aprobar",
        [
            feature.display_title or feature.title,
            (feature.spec or {}).get("summary", "")[:1500],
            f"Impacto estimado: {(feature.spec or {}).get('blast_radius', '—')}",
        ],
        "Revisar y decidir",
        feature.workspace,
        feature.id,
        "feature",
    )


def requester_feature_update(feature, heading, message):
    if feature.requested_by is None:
        return
    send(
        feature.requested_by.email,
        heading,
        heading,
        [greeting(feature.requested_by), message],
        "Ver mi seguimiento",
        support_url(door(feature.requested_by, feature.workspace), feature.id, "feature"),
    )
