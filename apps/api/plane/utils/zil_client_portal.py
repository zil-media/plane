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
    ZilPostReview,
)

logger = logging.getLogger("plane.api")

VISIBLE_LABEL = "Visible al cliente"
REVIEW_STATE = "Aprobación cliente"
SCHEDULED_STATE = "Programado"
CLIENT_FOLDER = "Cliente"
# marks the folder the seed made (Page.external_source), so a team's own "Cliente" folder is never adopted
CLIENT_FOLDER_SOURCE = "zil_client_portal"
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

# the four statuses the client reads instead of Ops' state names (the portal translates them)
STATUS_PREPARING = "preparing"
STATUS_REVIEW = "review"
STATUS_SCHEDULED = "scheduled"
STATUS_PUBLISHED = "published"


# ---------------------------------------------------------------------------
# Seeding (step 3 and the "Cliente" folder of step 7)
# ---------------------------------------------------------------------------


def seed_brand_content(project, user):
    """Give a brand project its content workflow (unless the workspace chose its clients' states),
    its "Visible al cliente" label, its calendar view and its "Cliente" folder.

    Idempotent and additive: what already exists by name is left as it is (a renamed or recoloured
    state stays so), so it is safe on an adopted project and in the backfill. Returns the portal.
    """
    from plane.utils.zil_client_states import template_states_for

    workspace_id = project.workspace_id
    # a workspace that chose its clients' states (a model project) keeps exactly those: the portal
    # adds no states of its own there (it only reads state names for the status it shows)
    if template_states_for(workspace_id) is None:
        states = {
            name.lower() for name in State.all_state_objects.filter(project=project).values_list("name", flat=True)
        }
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
                # posts go out on weekends too
                "calendar": {"layout": "month", "show_weekends": True},
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
        pk=page_id,
        kind=Page.FOLDER_KIND,
        archived_at__isnull=True,
        project_pages__project=project,
        project_pages__deleted_at__isnull=True,
    ).exists()


def _client_folder(project, user):
    """The project's "Cliente" folder made for the portal: the one the seed made, or a new one.

    A folder the team already had with that name is never adopted: what they kept in it would
    become visible to the client the moment the portal is turned on.
    """
    folder = (
        Page.objects.filter(
            project_pages__project=project,
            project_pages__deleted_at__isnull=True,
            kind=Page.FOLDER_KIND,
            archived_at__isnull=True,
            external_source=CLIENT_FOLDER_SOURCE,
        )
        .order_by("created_at")
        .first()
    )
    if folder is not None:
        return folder
    folder = Page.objects.create(
        name=CLIENT_FOLDER,
        kind=Page.FOLDER_KIND,
        external_source=CLIENT_FOLDER_SOURCE,
        external_id=str(project.id),
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


def portal_unit(workspace_slug):
    """Whose brand the portal wears: Meraki's for its units' brands, Zil's for the rest."""
    return "meraki" if str(workspace_slug or "").lower().startswith("meraki") else "zil"


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
        .select_related("project", "workspace")
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
        .select_related("brand_project__project", "brand_project__workspace")
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


def client_candidates(project):
    """The items the team can publish to the client: labelled "Visible al cliente", live, not cancelled."""
    return Issue.issue_objects.filter(project=project, pk__in=_visible_ids(project.id)).exclude(
        state__group="cancelled"
    )


def visible_issues(project):
    """The items the client sees: candidates the team already published to them."""
    return client_candidates(project).filter(zil_review__isnull=False)


def _visible_ids(project_id):
    return IssueLabel.objects.filter(
        project_id=project_id, label__name__iexact=VISIBLE_LABEL, label__deleted_at__isnull=True
    ).values("issue_id")


def simple_status(state):
    """One of the four statuses the client reads (a code: the portal shows it in their language)."""
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
    return (
        IssueLabel.objects.filter(
            issue_id=issue.id, label__name__iexact=VISIBLE_LABEL, label__deleted_at__isnull=True
        ).exists()
        and ZilPostReview.objects.filter(issue_id=issue.id).exists()
    )


def _folder_ids(portal):
    """([sub-folder ids], [page ids]) inside the portal's "Cliente" folder, at any depth; ([], []) when
    the folder is archived or unlinked (it hides everything inside it)."""
    if portal.pages_folder_id is None or not _is_live_folder(portal.pages_folder_id, portal.project):
        return [], []
    folders, pages = [], []
    frontier = [portal.pages_folder_id]
    seen = set(frontier)
    depth = 0
    while frontier and depth < Page.MAX_TREE_DEPTH:
        # a private page (or folder) is its owner's alone: never shown to the client, nor what is inside
        children = list(
            Page.objects.filter(parent_id__in=frontier, archived_at__isnull=True)
            .exclude(access=Page.PRIVATE_ACCESS)
            .values_list("id", "kind")
        )
        frontier = []
        for page_id, kind in children:
            if page_id in seen:
                continue
            seen.add(page_id)
            if kind == Page.FOLDER_KIND:
                frontier.append(page_id)
                folders.append(page_id)
            else:
                pages.append(page_id)
        depth += 1
    return folders, pages


def _in_project(portal, ids):
    return Page.objects.filter(
        pk__in=ids,
        archived_at__isnull=True,
        access=Page.PUBLIC_ACCESS,
        project_pages__project_id=portal.project_id,
        project_pages__deleted_at__isnull=True,
    ).distinct()


def folder_pages(portal):
    """The pages inside the portal's "Cliente" folder, at any depth (folders themselves left out)."""
    return _in_project(portal, _folder_ids(portal)[1])


def folder_tree(portal):
    """(sub-folders, pages) inside the "Cliente" folder, for the portal's Documentos tab."""
    folders, pages = _folder_ids(portal)
    return _in_project(portal, folders), _in_project(portal, pages)


def is_in_client_folder(page):
    """Whether a page is inside its project's "Cliente" folder (the portal shows it and its comments)."""
    portal = ZilClientPortal.objects.filter(project__project_pages__page=page).select_related("project").first()
    return portal is not None and folder_pages(portal).filter(pk=page.pk).exists()


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
        signature=f"Equipo de {project.name}",
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
        .select_related("user", "brand_project__project", "brand_project__workspace")
        .first()
    )
    if client is None or client.invited_at is None:
        return None
    if client.invited_at < timezone.now() - timedelta(days=INVITE_DAYS):
        return None
    if not client.user.is_active or client.user.is_bot:
        return None
    # a portal turned off, or a brand paused or gone, since the invitation: the link stops working
    mapping = client.brand_project
    if mapping.deleted_at is not None or mapping.project.deleted_at is not None or is_paused(mapping.project, mapping):
        return None
    if not ZilClientPortal.objects.filter(project_id=mapping.project_id, enabled=True).exists():
        return None
    return client


def use_invite(client):
    """Spend the link: True for the one request that does (two at once never both get in). Every
    other live invitation of the same account is spent with it."""
    spent = ZilBrandClient.objects.filter(pk=client.pk, invite_token_hash=client.invite_token_hash).update(
        invite_token_hash="", updated_at=timezone.now()
    )
    if spent != 1:
        return False
    ZilBrandClient.objects.filter(user_id=client.user_id).exclude(invite_token_hash="").update(
        invite_token_hash="", updated_at=timezone.now()
    )
    return True


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


def notify_clients_published(project, issues, portal):
    """The team published posts to the client: its clients get one email with all of them, the
    rounds of changes they have and until when."""
    from plane.utils.agent_pipeline import notify

    mapping = _portal_mapping(project.id)
    if mapping is None or not issues:
        return
    days = portal.change_days
    rounds = portal.change_rounds
    terms = []
    if rounds:
        terms.append(f"{rounds} {'ronda' if rounds == 1 else 'rondas'} de cambios")
    if days:
        terms.append(f"{days} {'día hábil' if days == 1 else 'días hábiles'}")
    link = portal_url(f"{project.id}" if len(issues) > 1 else f"{project.id}?post={issues[0].id}")
    count = len(issues)
    for email in _clients_of(mapping):
        notify.send(
            email,
            f"Tenés {count} {'publicación' if count == 1 else 'publicaciones'} para revisar en {project.name}",
            "Tenés publicaciones para revisar" if count > 1 else "Tenés una publicación para revisar",
            [
                "Hola,",
                f"El equipo publicó en tu calendario de {project.name}:",
                *[f"• {issue.name}" for issue in issues[:30]],
                (
                    f"Tenés {' y '.join(terms)} para pedir cambios."
                    if terms
                    else "Contanos qué te parece dejando tus cambios."
                ),
            ],
            "Ver el calendario" if count > 1 else "Ver la publicación",
            link,
            signature=f"Equipo de {project.name}",
        )


def publish_posts(portal, issue_ids, user):
    """Publish the chosen items to the client: each opens its window for changes now (an item already
    published keeps the one it has). Their clients get one email. Returns the newly published items."""
    project = portal.project
    chosen = list(client_candidates(project).filter(pk__in=issue_ids).order_by("target_date", "sequence_id"))
    already = set(ZilPostReview.objects.filter(issue__in=chosen).values_list("issue_id", flat=True))
    fresh = [issue for issue in chosen if issue.id not in already]
    now = timezone.now()
    ZilPostReview.objects.bulk_create(
        [
            ZilPostReview(
                issue=issue, project=project, started_at=now, published_by=user, created_by=user, updated_by=user
            )
            for issue in fresh
        ],
        ignore_conflicts=True,
    )
    if portal.enabled:
        notify_clients_published(project, fresh, portal)
    return fresh


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
            signature=f"Equipo de {project.name}",
        )


def _web_page_url(project, page):
    base = (settings.WEB_URL or settings.APP_BASE_URL or "").rstrip("/")
    return f"{base}/{project.workspace.slug}/projects/{project.id}/pages/{page.id}/?paneTab=client"


def notify_page_comment(page, comment, author):
    """A comment on a "Cliente" folder page: from a client, the CMs and Responsable get an email; from
    the team, the brand's clients do. Sent once the comment is saved."""
    from plane.utils.agent_pipeline import notify

    project_id = comment.project_id
    mapping = _portal_mapping(project_id)
    if mapping is None:
        return
    project = mapping.project
    text = (comment.comment_stripped or "").strip()[:600] or "(sin texto)"
    is_member = ProjectMember.objects.filter(project_id=project_id, member=author, is_active=True).exists()
    if not is_member:
        name = (author.display_name or author.first_name or author.email).strip()
        title = f"{name} (cliente) comentó en «{page.name or 'Sin título'}»"
        for user in _team_to_notify(mapping):
            notify.send(
                user.email,
                title,
                f"Comentario del cliente en {project.name}",
                [notify.greeting(user), f"{name} dejó un comentario en el documento «{page.name}»:", text],
                "Ver el documento",
                _web_page_url(project, page),
            )
        return
    link = portal_url(f"{project.id}?tab=documents&doc={page.id}")
    for email in _clients_of(mapping):
        notify.send(
            email,
            f"Te respondieron en {project.name}",
            "El equipo te respondió",
            ["Hola,", f"Hay una respuesta nueva en el documento «{page.name}»:", text],
            "Ver la respuesta",
            link,
            signature=f"Equipo de {project.name}",
        )


# --- rounds of changes ---------------------------------------------------------------------------


def review_for(issue):
    """The post's publication to the client (its window for changes), or None if not published."""
    return ZilPostReview.objects.filter(issue_id=issue.id).first()


# Zil works from Argentina: the business days of a workspace still on the default UTC are Buenos Aires'
ZIL_TIMEZONE = "America/Argentina/Buenos_Aires"


def _brand_timezone(portal):
    from zoneinfo import ZoneInfo

    name = getattr(portal.project.workspace, "timezone", "") or "UTC"
    try:
        return ZoneInfo(ZIL_TIMEZONE if name == "UTC" else name)
    except (KeyError, ValueError):
        return ZoneInfo(ZIL_TIMEZONE)


def add_business_days(start, days, tz):
    """`start` plus `days` business days (Monday to Friday) in `tz`, at the same time of day: a review
    opened on Friday 18:00 with 1 day ends Monday 18:00; one opened on Saturday, Monday too."""
    current = start.astimezone(tz)
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current


def review_status(portal, review, now=None):
    """What the client can still do on a post: rounds left and until when.

    {rounds, used, left, deadline, open, reason}: `deadline` counts the brand's business days from the
    first review; `rounds`/`left`/`deadline` are None when the brand
    sets no limit; `reason` says why it is closed: "not_started" (not published yet), "expired"
    or "rounds_used".
    """
    now = now or timezone.now()
    rounds = portal.change_rounds or None
    used = review.rounds_used if review else 0
    deadline = (
        add_business_days(review.started_at, portal.change_days, _brand_timezone(portal))
        if review and portal.change_days
        else None
    )
    reason = None
    if review is None:
        reason = "not_started"
    elif deadline is not None and now >= deadline:
        reason = "expired"
    elif rounds is not None and used >= rounds:
        reason = "rounds_used"
    return {
        "rounds": rounds,
        "used": used,
        "left": max(0, rounds - used) if rounds is not None else None,
        "deadline": deadline.isoformat() if deadline else None,
        "open": reason is None,
        "reason": reason,
    }


def notify_team_of_client_round(issue, comments, author, round_number):
    """A client sent a round of changes: one notice and one email for all of them."""
    from plane.utils.agent_pipeline import notify

    mapping = _portal_mapping(issue.project_id)
    if mapping is None or not comments:
        return
    project = mapping.project
    name = (author.display_name or author.first_name or author.email).strip()
    title = f"{name} (cliente) pidió cambios en {issue.name} (ronda {round_number})"
    url = _web_issue_url(project, issue)
    lines = [(comment.comment_stripped or "").strip()[:300] for comment in comments]
    first = comments[0]
    for user in _team_to_notify(mapping):
        Notification.objects.create(
            workspace_id=project.workspace_id,
            project_id=project.id,
            entity_identifier=issue.id,
            entity_name="issue",
            title=title,
            message_html="".join(comment.comment_html or "" for comment in comments),
            message_stripped="\n".join(lines),
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
                    "id": str(first.id),
                    "verb": "created",
                    "field": "comment",
                    "actor": str(author.id),
                    "new_value": first.comment_html,
                    "old_value": None,
                    "issue_comment": str(first.id),
                },
            },
        )
        notify.send(
            user.email,
            title,
            f"Cambios del cliente en {project.name}",
            [
                notify.greeting(user),
                f"{name} mandó {len(comments)} {'cambios' if len(comments) != 1 else 'cambio'} en «{issue.name}» "
                f"(ronda {round_number}):",
                *[f"• {line or '(sin texto)'}" for line in lines[:20]],
                "Respondele desde Zil Ops marcando el comentario como externo, así le llega.",
            ],
            "Ver la publicación",
            url,
        )


def _json(raw):
    import json

    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        return {}


def dispatch_portal_events(
    type, issue_id, actor_id, issue_activities, project_id=None, requested_data=None, current_instance=None
):
    """Called by the issue activity task after each change: the portal's notices, from any path."""
    if issue_id is None or type not in (
        # (the client hears of a post when the team publishes it, publish_posts, not by its state)
        "comment.activity.created",
        "comment.activity.updated",
    ):
        return
    # most activity is in projects without a portal: one cheap query and out
    if project_id is not None and not ZilClientPortal.objects.filter(project_id=project_id, enabled=True).exists():
        return
    issue = Issue.issue_objects.filter(pk=issue_id).select_related("state", "project").first()
    if issue is None:
        return
    from plane.db.models import IssueComment, User

    author = User.objects.filter(pk=actor_id).first()
    if author is None:
        return
    is_member = ProjectMember.objects.filter(project_id=issue.project_id, member=author, is_active=True).exists()
    if type == "comment.activity.updated":
        # an internal comment the team made external: the client hears it like a new answer
        before, after = _json(current_instance), _json(requested_data)
        if not is_member or before.get("access") != "INTERNAL" or after.get("access") != "EXTERNAL":
            return
        comment = IssueComment.objects.filter(pk=before.get("id"), issue_id=issue.id, access="EXTERNAL").first()
        if comment is not None:
            notify_clients_reply(issue, comment)
        return
    # a round of changes: its comments come one activity each, the team hears it once (the first)
    round_info = _json(requested_data).get("zil_round") or {}
    if round_info and not round_info.get("first"):
        return
    for activity in issue_activities:
        if activity.field != "comment" or activity.issue_comment_id is None:
            continue
        comment = IssueComment.objects.filter(
            pk=activity.issue_comment_id, issue_id=issue.id, access="EXTERNAL"
        ).first()
        if comment is None:
            continue
        if is_member:
            notify_clients_reply(issue, comment)
        elif ZilBrandClient.objects.filter(brand_project__project_id=issue.project_id, user=author).exists():
            if round_info:
                ids = round_info.get("comments") or [str(comment.id)]
                round_comments = sorted(
                    IssueComment.objects.filter(pk__in=ids, issue_id=issue.id), key=lambda c: ids.index(str(c.id))
                )
                notify_team_of_client_round(issue, round_comments, author, round_info.get("round") or 1)
            else:
                notify_team_of_client_comment(issue, comment, author)
