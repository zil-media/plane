# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""A brand's client portal: its content calendar and its "Cliente" pages folder, for its clients.

A brand project gets a content workflow (states, network/format labels, "Visible al cliente", the
"Calendario de contenidos" view) and a "Cliente" pages folder when Zil makes or adopts it, and the
backfill command (`zil_seed_brand_content`) gives them to the brands that already exist.

Clients (`ZilBrandClient`, pushed by Zil) are never project or workspace members: what they see is
what the portal API (`plane.space.views.zil_portal`) hands them, and nothing else. A client sees a
brand's portal only while the team has it on and the brand is not archived (suspended or dropped in
Zil: "acceso en pausa"); items only with the "Visible al cliente" label; documents only inside the
brand's "Cliente" folder; comments only the external ones.

Their way in is a Marketwise-style invitation: an email with a single-use link that lasts 7 days,
where they choose a password; after that they sign in with email and password.
"""

# Python imports
import hashlib
import logging
import secrets
from datetime import timedelta

# Django imports
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

# Module imports
from plane.db.models import (
    Issue,
    IssueLabel,
    IssueView,
    Label,
    Notification,
    Page,
    Project,
    ProjectMember,
    ProjectPage,
    State,
    ZilBrandClient,
    ZilBrandOps,
    ZilBrandProject,
    ZilBrandResponsible,
    ZilClientPortal,
)

logger = logging.getLogger("plane.api")

VISIBLE_LABEL = "Visible al cliente"
REVIEW_STATE = "Aprobación cliente"
SCHEDULED_STATE = "Programado"
CLIENT_FOLDER = "Cliente"
CALENDAR_VIEW = "Calendario de contenidos"
INVITE_DAYS = 7

# after every DEFAULT_STATES entry (max sequence 65000), in workflow order
CONTENT_STATES = [
    {"name": "Idea", "color": "#A3A3A3", "group": "backlog", "sequence": 100000},
    {"name": "Guion", "color": "#3F76FF", "group": "started", "sequence": 105000},
    {"name": "Diseño", "color": "#8B5CF6", "group": "started", "sequence": 110000},
    {"name": REVIEW_STATE, "color": "#F59E0B", "group": "started", "sequence": 115000},
    {"name": SCHEDULED_STATE, "color": "#26B5CE", "group": "started", "sequence": 120000},
    {"name": "Publicado", "color": "#22C55E", "group": "completed", "sequence": 125000},
]
NETWORK_LABELS = [
    {"name": "Instagram", "color": "#E1306C"},
    {"name": "TikTok", "color": "#111111"},
    {"name": "Facebook", "color": "#1877F2"},
    {"name": "LinkedIn", "color": "#0A66C2"},
    {"name": "YouTube", "color": "#FF0000"},
]
FORMAT_LABELS = [
    {"name": "Reel", "color": "#F97316"},
    {"name": "Post", "color": "#3B82F6"},
    {"name": "Carrusel", "color": "#10B981"},
    {"name": "Historia", "color": "#EC4899"},
]
CONTENT_LABELS = [*NETWORK_LABELS, *FORMAT_LABELS, {"name": VISIBLE_LABEL, "color": "#16A34A"}]
NETWORKS = {label["name"].lower() for label in NETWORK_LABELS}

# what the client reads instead of Ops' state names
STATUS_PREPARING = "En preparación"
STATUS_REVIEW = "Para revisar"
STATUS_SCHEDULED = "Programada"
STATUS_PUBLISHED = "Publicada"


# ---------------------------------------------------------------------------
# Seeding (step 3 and the "Cliente" folder of step 7)
# ---------------------------------------------------------------------------


def seed_brand_content(project, user):
    """Give a brand project its content workflow, its calendar view and its "Cliente" folder.

    Idempotent and additive: what already exists by name is left as it is (a renamed or recoloured
    state stays so), so it is safe on an adopted project and in the backfill. Returns the portal.
    """
    workspace_id = project.workspace_id
    states = {name.lower() for name in State.all_state_objects.filter(project=project).values_list("name", flat=True)}
    State.objects.bulk_create(
        [
            State(
                name=state["name"],
                color=state["color"],
                group=state["group"],
                sequence=state["sequence"],
                project=project,
                workspace_id=workspace_id,
                created_by=user,
            )
            for state in CONTENT_STATES
            if state["name"].lower() not in states
        ]
    )
    labels = {name.lower() for name in Label.objects.filter(project=project).values_list("name", flat=True)}
    Label.objects.bulk_create(
        [
            Label(name=label["name"], color=label["color"], project=project, workspace_id=workspace_id, created_by=user)
            for label in CONTENT_LABELS
            if label["name"].lower() not in labels
        ]
    )
    if not IssueView.objects.filter(project=project, name=CALENDAR_VIEW).exists():
        IssueView.objects.create(
            name=CALENDAR_VIEW,
            description="Las publicaciones de la marca por fecha de publicación.",
            query={},
            filters={},
            display_filters={
                "group_by": None,
                "order_by": "-created_at",
                "type": None,
                "sub_issue": False,
                "show_empty_groups": True,
                "layout": "calendar",
                "calendar_date_range": "",
            },
            access=1,
            owned_by=user,
            project=project,
            workspace_id=workspace_id,
            created_by=user,
        )
    if not project.issue_views_view:
        # the calendar view is where the team plans the brand's content
        Project.objects.filter(pk=project.pk).update(issue_views_view=True)
        project.issue_views_view = True

    portal = ZilClientPortal.objects.filter(project=project).first()
    if portal is None:
        try:
            with transaction.atomic():
                portal = ZilClientPortal.objects.create(project=project, created_by=user)
        except IntegrityError:
            portal = ZilClientPortal.objects.get(project=project)
    if portal.pages_folder_id is None or not _is_live_folder(portal.pages_folder_id, project):
        portal.pages_folder = _client_folder(project, user)
        portal.save(update_fields=["pages_folder", "updated_at"])
    return portal


def _is_live_folder(page_id, project):
    return Page.objects.filter(
        pk=page_id, kind=Page.FOLDER_KIND, archived_at__isnull=True, project_pages__project=project
    ).exists()


def _client_folder(project, user):
    """The project's top-level "Cliente" folder: the one there is, or a new one."""
    folder = (
        Page.objects.filter(
            project_pages__project=project,
            project_pages__deleted_at__isnull=True,
            kind=Page.FOLDER_KIND,
            parent__isnull=True,
            archived_at__isnull=True,
            name__iexact=CLIENT_FOLDER,
        )
        .order_by("created_at")
        .first()
    )
    if folder is not None:
        return folder
    folder = Page.objects.create(
        name=CLIENT_FOLDER,
        kind=Page.FOLDER_KIND,
        workspace_id=project.workspace_id,
        owned_by=user,
        access=Page.PUBLIC_ACCESS,
        created_by=user,
    )
    ProjectPage.objects.create(project=project, page=folder, workspace_id=project.workspace_id, created_by=user)
    return folder


# ---------------------------------------------------------------------------
# What a client can see
# ---------------------------------------------------------------------------


class PortalDenied(Exception):
    """`paused` is True when the brand is archived: its clients see "Acceso en pausa"."""

    def __init__(self, paused=False):
        super().__init__("paused" if paused else "not found")
        self.paused = paused


def is_paused(project, mapping):
    return project.archived_at is not None or mapping.status == ZilBrandProject.ARCHIVED


def portal_for(user, project_id):
    """(portal, project, mapping, is_client) when `user` may see this brand's portal.

    A client of the brand, or a member of its project (the team previews what the client sees).
    Anything else, including a portal that is off, raises PortalDenied() (a 404: it never says the
    portal exists); a client of an archived brand raises PortalDenied(paused=True).
    """
    mapping = (
        ZilBrandProject.objects.filter(
            project_id=project_id,
            kind=ZilBrandProject.BRAND_KIND,
            project__deleted_at__isnull=True,
        )
        .select_related("project")
        .first()
    )
    if mapping is None:
        raise PortalDenied()
    project = mapping.project
    portal = ZilClientPortal.objects.filter(project=project).first()
    is_member = ProjectMember.objects.filter(project=project, member=user, is_active=True).exists()
    is_client = (
        not is_member and user.is_active and ZilBrandClient.objects.filter(brand_project=mapping, user=user).exists()
    )
    if not (is_member or is_client):
        raise PortalDenied()
    if portal is None or not portal.enabled:
        raise PortalDenied()
    if is_client and is_paused(project, mapping):
        raise PortalDenied(paused=True)
    return portal, project, mapping, is_client


def client_brands(user):
    """The brands whose portal `user` is a client of: [(mapping, paused)], by name."""
    rows = (
        ZilBrandClient.objects.filter(
            user=user,
            brand_project__kind=ZilBrandProject.BRAND_KIND,
            brand_project__deleted_at__isnull=True,
            brand_project__project__deleted_at__isnull=True,
            brand_project__project__zil_client_portal__enabled=True,
        )
        .select_related("brand_project__project")
        .order_by("brand_project__project__name")
    )
    seen = set()
    brands = []
    for row in rows:
        mapping = row.brand_project
        if mapping.project_id in seen:
            continue
        seen.add(mapping.project_id)
        brands.append((mapping, is_paused(mapping.project, mapping)))
    return brands


def is_portal_client(user):
    """Whether `user` is a client of any brand (with an account), whatever the portal's state."""
    return ZilBrandClient.objects.filter(
        user=user, brand_project__deleted_at__isnull=True, brand_project__project__deleted_at__isnull=True
    ).exists()


def visible_issues(project):
    """The project's items the client sees: labelled "Visible al cliente", live, not cancelled."""
    return Issue.issue_objects.filter(project=project, pk__in=_visible_ids(project.id)).exclude(
        state__group="cancelled"
    )


def _visible_ids(project_id):
    return IssueLabel.objects.filter(
        project_id=project_id, label__name__iexact=VISIBLE_LABEL, label__deleted_at__isnull=True
    ).values("issue_id")


def simple_status(state):
    """One of the four words the client reads."""
    if state is None:
        return STATUS_PREPARING
    name = (state.name or "").strip().lower()
    if state.group == "completed":
        return STATUS_PUBLISHED
    if name == SCHEDULED_STATE.lower():
        return STATUS_SCHEDULED
    if name == REVIEW_STATE.lower():
        return STATUS_REVIEW
    return STATUS_PREPARING


def is_visible(issue):
    return IssueLabel.objects.filter(
        issue_id=issue.id, label__name__iexact=VISIBLE_LABEL, label__deleted_at__isnull=True
    ).exists()


def folder_pages(portal):
    """The pages inside the portal's "Cliente" folder, at any depth (folders themselves left out)."""
    if portal.pages_folder_id is None:
        return Page.objects.none()
    ids = []
    frontier = [portal.pages_folder_id]
    seen = set(frontier)
    depth = 0
    while frontier and depth < Page.MAX_TREE_DEPTH:
        children = list(Page.objects.filter(parent_id__in=frontier, archived_at__isnull=True).values_list("id", "kind"))
        frontier = []
        for page_id, kind in children:
            if page_id in seen:
                continue
            seen.add(page_id)
            if kind == Page.FOLDER_KIND:
                frontier.append(page_id)
            else:
                ids.append(page_id)
        depth += 1
    return Page.objects.filter(
        pk__in=ids,
        archived_at__isnull=True,
        project_pages__project_id=portal.project_id,
        project_pages__deleted_at__isnull=True,
    ).distinct()


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def portal_url(path=""):
    """An absolute URL inside the portal (the `space` app)."""
    base = (settings.SPACE_BASE_URL or settings.WEB_URL or settings.APP_BASE_URL or "").rstrip("/")
    space_path = (settings.SPACE_BASE_PATH or "/spaces/").strip("/")
    return f"{base}/{space_path}/portal/{path.lstrip('/')}"


def needs_password(user):
    return bool(user.is_password_autoset or not user.has_usable_password())


def invite_client(client):
    """Send `client` a new single-use link to the portal (the old one stops working). Returns whether sent.

    Only a client with an account, whose brand's portal is on and not paused, is invited.
    """
    from plane.utils.agent_pipeline import notify

    mapping = client.brand_project
    project = mapping.project
    portal = ZilClientPortal.objects.filter(project=project).first()
    if client.user_id is None or portal is None or not portal.enabled or is_paused(project, mapping):
        return False
    token = secrets.token_urlsafe(32)
    client.invite_token_hash = _hash(token)
    client.invited_at = timezone.now()
    client.save(update_fields=["invite_token_hash", "invited_at", "updated_at"])
    link = portal_url(f"invite/{token}")
    notify.send(
        client.email,
        f"Tu calendario de {project.name}",
        f"Tu calendario de {project.name}",
        [
            "Hola,",
            f"El equipo de {project.name} te invitó a ver tu calendario de contenidos y tus documentos.",
            "Desde ahí podés ver qué se publica y cuándo, y dejarnos tus comentarios.",
            f"El link vence en {INVITE_DAYS} días.",
        ],
        "Ver mi calendario",
        link,
    )
    return True


def invite_pending(portal):
    """Invite every client of the portal's brand who was never invited. Returns how many."""
    sent = 0
    for client in ZilBrandClient.objects.filter(
        brand_project__project_id=portal.project_id, user__isnull=False, invited_at__isnull=True
    ).select_related("brand_project__project", "user"):
        sent += int(invite_client(client))
    return sent


def client_for_token(token):
    """The client whose live invitation this token is, or None (unknown, used or expired)."""
    token = str(token or "")
    if not token or len(token) > 200:
        return None
    client = (
        ZilBrandClient.objects.filter(invite_token_hash=_hash(token), user__isnull=False)
        .select_related("user", "brand_project__project")
        .first()
    )
    if client is None or client.invited_at is None:
        return None
    if client.invited_at < timezone.now() - timedelta(days=INVITE_DAYS):
        return None
    if not client.user.is_active or client.user.is_bot:
        return None
    return client


def use_invite(client):
    """The link works once: every live invitation of the same account is spent with it."""
    ZilBrandClient.objects.filter(user_id=client.user_id).exclude(invite_token_hash="").update(
        invite_token_hash="", updated_at=timezone.now()
    )


def access_status(client):
    """What Zil Workspace shows for a client: active (has signed in), invited, expired or never."""
    user = client.user
    if user is not None and user.last_login_time and not needs_password(user):
        return "active"
    if client.invited_at is None:
        return "never"
    if client.invite_token_hash and client.invited_at >= timezone.now() - timedelta(days=INVITE_DAYS):
        return "invited"
    return "expired"


def client_access(mapping):
    """[{email, status, invitedAt, lastLogin}] of a brand project's clients, for the roster answer."""
    out = []
    for client in ZilBrandClient.objects.filter(brand_project=mapping).select_related("user").order_by("email"):
        out.append(
            {
                "email": client.email,
                "status": access_status(client),
                "invitedAt": client.invited_at.isoformat() if client.invited_at else None,
                "lastLogin": client.user.last_login_time.isoformat()
                if client.user is not None and client.user.last_login_time
                else None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Notices (step 6)
# ---------------------------------------------------------------------------


def _team_to_notify(mapping):
    """The brand's CMs and this unit's Responsable who are on its project."""
    users = {}
    ops = ZilBrandOps.objects.filter(zil_brand_id=mapping.zil_brand_id).first()
    if ops is not None:
        for user in ops.community_managers.filter(is_active=True, is_bot=False):
            users[user.id] = user
    responsible = (
        ZilBrandResponsible.objects.filter(zil_brand_id=mapping.zil_brand_id, workspace_id=mapping.workspace_id)
        .select_related("member")
        .first()
    )
    if responsible is not None and responsible.member.is_active:
        users[responsible.member.id] = responsible.member
    members = set(
        ProjectMember.objects.filter(project_id=mapping.project_id, is_active=True, member_id__in=users).values_list(
            "member_id", flat=True
        )
    )
    return [user for user_id, user in users.items() if user_id in members]


def _web_issue_url(project, issue):
    base = (settings.WEB_URL or settings.APP_BASE_URL or "").rstrip("/")
    return f"{base}/{project.workspace.slug}/browse/{project.identifier}-{issue.sequence_id}/"


def _clients_of(mapping):
    return list(
        ZilBrandClient.objects.filter(
            brand_project=mapping, user__isnull=False, user__is_active=True, user__last_login_time__isnull=False
        ).values_list("email", flat=True)
    )


def _portal_mapping(project_id):
    """The brand mapping of a project whose portal is on and not paused, else None."""
    mapping = (
        ZilBrandProject.objects.filter(project_id=project_id, kind=ZilBrandProject.BRAND_KIND)
        .select_related("project__workspace")
        .first()
    )
    if mapping is None or is_paused(mapping.project, mapping):
        return None
    if not ZilClientPortal.objects.filter(project_id=project_id, enabled=True).exists():
        return None
    return mapping


def notify_team_of_client_comment(issue, comment, author):
    """A client commented: the brand's CMs and Responsable get an in-app notice and an email."""
    from plane.utils.agent_pipeline import notify

    mapping = _portal_mapping(issue.project_id)
    if mapping is None:
        return
    project = mapping.project
    name = (author.display_name or author.first_name or author.email).strip()
    title = f"{name} (cliente) comentó en {issue.name}"
    url = _web_issue_url(project, issue)
    for user in _team_to_notify(mapping):
        Notification.objects.create(
            workspace_id=project.workspace_id,
            project_id=project.id,
            entity_identifier=issue.id,
            entity_name="issue",
            title=title,
            message_html=comment.comment_html or "<p></p>",
            message_stripped=comment.comment_stripped,
            sender="in_app:issue_activities:comment",
            triggered_by=author,
            receiver=user,
            data={
                "issue": {
                    "id": str(issue.id),
                    "name": issue.name,
                    "identifier": project.identifier,
                    "sequence_id": issue.sequence_id,
                    "state_name": issue.state.name if issue.state else None,
                    "state_group": issue.state.group if issue.state else None,
                },
                "issue_activity": {
                    "id": str(comment.id),
                    "verb": "created",
                    "field": "comment",
                    "actor": str(author.id),
                    "new_value": comment.comment_html,
                    "old_value": None,
                    "issue_comment": str(comment.id),
                },
            },
        )
        notify.send(
            user.email,
            title,
            f"Comentario del cliente en {project.name}",
            [
                notify.greeting(user),
                f"{name} dejó un comentario en «{issue.name}»:",
                (comment.comment_stripped or "").strip()[:600] or "(sin texto)",
                "Respondele desde Zil Ops marcando el comentario como externo, así le llega.",
            ],
            "Ver la publicación",
            url,
        )


def notify_clients_review(issue):
    """An item the client sees went to "Aprobación cliente": its clients get an email."""
    from plane.utils.agent_pipeline import notify

    mapping = _portal_mapping(issue.project_id)
    if mapping is None or not is_visible(issue):
        return
    project = mapping.project
    link = portal_url(f"{project.id}?post={issue.id}")
    for email in _clients_of(mapping):
        notify.send(
            email,
            f"Tenés una publicación para revisar en {project.name}",
            "Tenés una publicación para revisar",
            [
                "Hola,",
                f"«{issue.name}» está lista para que la veas.",
                "Contanos qué te parece dejando un comentario.",
            ],
            "Ver la publicación",
            link,
        )


def notify_clients_reply(issue, comment):
    """The team answered with an external comment: the brand's clients get an email."""
    from plane.utils.agent_pipeline import notify

    mapping = _portal_mapping(issue.project_id)
    if mapping is None or not is_visible(issue):
        return
    project = mapping.project
    link = portal_url(f"{project.id}?post={issue.id}")
    for email in _clients_of(mapping):
        notify.send(
            email,
            f"Te respondieron en {project.name}",
            "El equipo te respondió",
            [
                "Hola,",
                f"Hay una respuesta nueva en «{issue.name}»:",
                (comment.comment_stripped or "").strip()[:600] or "(sin texto)",
            ],
            "Ver la respuesta",
            link,
        )


def dispatch_portal_events(type, issue_id, actor_id, issue_activities):
    """Called by the issue activity task after each change: the portal's notices, from any path."""
    if issue_id is None or type not in ("issue.activity.updated", "comment.activity.created"):
        return
    issue = Issue.issue_objects.filter(pk=issue_id).select_related("state", "project").first()
    if issue is None:
        return
    if type == "issue.activity.updated":
        to_review = any(
            activity.field == "state" and (activity.new_value or "").strip().lower() == REVIEW_STATE.lower()
            for activity in issue_activities
        )
        if to_review and issue.state is not None and issue.state.name.strip().lower() == REVIEW_STATE.lower():
            notify_clients_review(issue)
        return
    from plane.db.models import IssueComment, User

    for activity in issue_activities:
        if activity.field != "comment" or activity.issue_comment_id is None:
            continue
        comment = IssueComment.objects.filter(pk=activity.issue_comment_id, access="EXTERNAL").first()
        if comment is None:
            continue
        author = User.objects.filter(pk=actor_id).first()
        if author is None:
            continue
        is_member = ProjectMember.objects.filter(project_id=issue.project_id, member=author, is_active=True).exists()
        if is_member:
            notify_clients_reply(issue, comment)
        elif ZilBrandClient.objects.filter(brand_project__project_id=issue.project_id, user=author).exists():
            notify_team_of_client_comment(issue, comment, author)
