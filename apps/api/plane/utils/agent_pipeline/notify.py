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


# The spec's blast_radius, said like the board says it (helpdesk.impact.*).
IMPACT = {"low": "bajo", "medium": "medio", "high": "alto"}


def send_admins(subject, heading, paragraphs, cta_label, workspace, item_id, kind="bug", exclude=None):
    """One email per admin, each with a link that opens for them (see door). `exclude`: the admin who
    just did it (filed it themselves) doesn't need to hear about it."""
    for admin in admin_users():
        if exclude is not None and admin.id == exclude.id:
            continue
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
            *(
                # A code fix: CI resolves it when the deploy starts, and trying right away would still
                # hit the old version. A person closing it by hand deploys nothing.
                [
                    "El cambio se está publicando y debería verse en unos minutos.",
                    "Si después de eso vuelve a pasar, respondé desde tu seguimiento y lo miramos de nuevo.",
                ]
                if bug.fixed_at or bug.commit_hash
                else ["Si vuelve a pasar, respondé desde tu seguimiento y lo miramos de nuevo."]
            ),
        ],
        "Ver mi seguimiento",
        support_url(door(bug.reported_by, bug.workspace), bug.id),
    )


def bug_user_guidance(bug):
    # Only someone who reported it by hand gets told: an automatic crash report's reported_by is just
    # the first person it happened to.
    if bug.source != bug.Source.MANUAL or bug.reported_by is None:
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
    # Only someone who reported it by hand gets told: an automatic crash report's reported_by is just
    # the first person it happened to.
    if bug.source != bug.Source.MANUAL or bug.reported_by is None:
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
    # Only someone who reported it by hand gets told: an automatic crash report's reported_by is just
    # the first person it happened to.
    if bug.source != bug.Source.MANUAL or bug.reported_by is None:
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
        exclude=bug.reported_by,
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
        exclude=feature.requested_by,
    )


def admins_feature_needs_decision(feature):
    spec = feature.spec or {}
    # Ops ya lo hace: "listo para aprobar" invitaba a aprobar un build para nada. Lo que toca es
    # rechazarla explicándole cómo (el motivo le llega a quien pidió).
    exists = bool(spec.get("already_exists"))
    send_admins(
        "Una sugerencia espera tu decisión",
        "Según el análisis, esto ya existe" if exists else "Hay un análisis listo para aprobar",
        [
            feature.display_title or feature.title,
            spec.get("summary", "")[:1500],
            "No hay nada que construir: rechazala explicándole cómo hacerlo."
            if exists
            else f"Impacto estimado: {IMPACT.get(spec.get('blast_radius'), '—')}",
        ],
        "Revisar y decidir",
        feature.workspace,
        feature.id,
        "feature",
    )


def requester_feature_approved(feature, building):
    """Approved, said as what actually happened: it only starts when the build lane has room."""
    if building:
        requester_feature_update(
            feature,
            "Tu sugerencia se empieza a construir",
            "Analizamos tu sugerencia y quedó aprobada. Ya empezamos a construirla; podés seguir el avance.",
        )
    else:
        requester_feature_update(
            feature,
            "Tu sugerencia quedó aprobada",
            "Analizamos tu sugerencia y quedó aprobada. El desarrollo arranca apenas se libere el turno; "
            "podés seguir el avance.",
        )


def requester_is_admin(feature):
    """The requester is also an admin: the admins' email about the same event already reaches them,
    with the action in it, so the requester version would be a second email saying less."""
    from plane.utils.agent_pipeline.permissions import is_instance_admin

    return is_instance_admin(feature.requested_by)


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
