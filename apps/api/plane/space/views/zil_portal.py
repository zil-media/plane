# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""The brand client portal's API (the `space` app's /portal screens).

Every endpoint goes through `portal_for` (plane.utils.zil_client_portal): a client of the brand or a
member of its project, a portal that is on, a brand that is not paused. Anything else is a 404 that
never says the portal exists; a paused brand answers 403 `{"paused": true}` so the client reads
"Acceso en pausa". What leaves here is a whitelist: no assignees, priority, estimates, cycles,
modules, sub-items, relations, activity or internal comments.
"""

# Python imports
import json
from datetime import date

# Django imports
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils import timezone
from django.utils.html import escape

# Third party imports
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from zxcvbn import zxcvbn

# Module imports
from plane.authentication.utils.login import user_login
from plane.bgtasks.issue_activities_task import issue_activity
from plane.db.models import FileAsset, IssueComment, IssueLabel, IssueLink, ProjectMember
from plane.settings.storage import S3Storage
from plane.utils.zil_client_portal import (
    REVIEW_STATE,
    VISIBLE_LABEL,
    NETWORKS,
    PortalDenied,
    client_brands,
    client_for_token,
    folder_pages,
    needs_password,
    portal_for,
    simple_status,
    use_invite,
    visible_issues,
)

from .base import BaseAPIView

MAX_POSTS = 500
MAX_COMMENTS = 500
MAX_DOCUMENTS = 300
MAX_COMMENT = 5000
MEDIA_TYPES = ("image/", "video/")


def _denied(exc, project=None):
    if exc.paused:
        body = {"paused": True}
        if project is not None:
            body["name"] = project.name
        return Response(body, status=status.HTTP_403_FORBIDDEN)
    return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)


def _brand(mapping, paused=False):
    project = mapping.project
    image = (project.logo_props or {}).get("image") or {}
    return {
        "id": str(project.id),
        "name": project.name,
        "logo_url": mapping.logo_url or image.get("url") or None,
        "color": mapping.color or None,
        "paused": paused,
    }


def _asset_url(project_id, asset_id):
    return f"/api/public/portal/{project_id}/assets/{asset_id}/"


def _media(project_id, assets):
    return [
        {
            "id": str(asset.id),
            "name": (asset.attributes or {}).get("name") or "",
            "type": (asset.attributes or {}).get("type") or "",
            "url": _asset_url(project_id, asset.id),
        }
        for asset in assets
    ]


def _attachments(issue_ids):
    """{issue_id: [assets]} of uploaded image/video attachments, oldest first."""
    out = {}
    assets = FileAsset.objects.filter(
        issue_id__in=issue_ids,
        entity_type=FileAsset.EntityTypeContext.ISSUE_ATTACHMENT,
        is_uploaded=True,
        is_deleted=False,
    ).order_by("created_at")
    for asset in assets:
        kind = str((asset.attributes or {}).get("type") or "").lower()
        if kind.startswith(MEDIA_TYPES):
            out.setdefault(asset.issue_id, []).append(asset)
    return out


def _labels(issue_ids):
    """{issue_id: [{name, color}]}, without the "Visible al cliente" marker."""
    out = {}
    rows = (
        IssueLabel.objects.filter(issue_id__in=issue_ids, label__deleted_at__isnull=True)
        .exclude(label__name__iexact=VISIBLE_LABEL)
        .values_list("issue_id", "label__name", "label__color")
        .order_by("label__name")
    )
    for issue_id, name, color in rows:
        out.setdefault(issue_id, []).append({"name": name, "color": color})
    return out


def _post(issue, labels, media):
    network = next((label["name"] for label in labels if label["name"].lower() in NETWORKS), None)
    thumb = media[0] if media else None
    return {
        "id": str(issue.id),
        "name": issue.name,
        "publish_date": issue.target_date.isoformat() if issue.target_date else None,
        "status": simple_status(issue.state),
        "status_color": issue.state.color if issue.state else None,
        "network": network,
        "labels": labels,
        "thumbnail": _media(issue.project_id, [thumb])[0] if thumb else None,
    }


def _parse_date(raw):
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


class PortalBaseEndpoint(BaseAPIView):
    """Signed-in only (BaseAPIView: IsAuthenticated + session)."""

    def guard(self, request, project_id):
        return portal_for(request.user, project_id)


class PortalBrandsEndpoint(PortalBaseEndpoint):
    """GET: the brands whose portal the signed-in person is a client of ("Mis marcas")."""

    def get(self, request):
        return Response({"brands": [_brand(mapping, paused) for mapping, paused in client_brands(request.user)]})


class PortalBrandEndpoint(PortalBaseEndpoint):
    """GET: the brand's header (name, logo, color); `preview` when a team member is looking."""

    def get(self, request, project_id):
        try:
            _, project, mapping, is_client = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        return Response({**_brand(mapping), "preview": not is_client})


class PortalPostsEndpoint(PortalBaseEndpoint):
    """GET ?start=YYYY-MM-DD&end=YYYY-MM-DD: the calendar's posts in that range and those to review."""

    def get(self, request, project_id):
        try:
            _, project, _, _ = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        issues = visible_issues(project).select_related("state")
        start = _parse_date(request.query_params.get("start"))
        end = _parse_date(request.query_params.get("end"))
        dated = issues.filter(target_date__isnull=False)
        if start:
            dated = dated.filter(target_date__gte=start)
        if end:
            dated = dated.filter(target_date__lte=end)
        dated = list(dated.order_by("target_date", "sequence_id")[:MAX_POSTS])
        review = list(issues.filter(state__name__iexact=REVIEW_STATE).order_by("target_date", "sequence_id")[:50])
        ids = {issue.id for issue in dated} | {issue.id for issue in review}
        labels = _labels(ids)
        media = _attachments(ids)
        return Response(
            {
                "posts": [_post(i, labels.get(i.id, []), media.get(i.id, [])) for i in dated],
                "to_review": [_post(i, labels.get(i.id, []), media.get(i.id, [])) for i in review],
            }
        )


class PortalPostEndpoint(PortalBaseEndpoint):
    """GET: one post as the client sees it: copy, media, links, date and simple status."""

    def get(self, request, project_id, issue_id):
        try:
            _, project, _, _ = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        issue = visible_issues(project).select_related("state").filter(pk=issue_id).first()
        if issue is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        labels = _labels([issue.id]).get(issue.id, [])
        media = _attachments([issue.id]).get(issue.id, [])
        links = [
            {"title": link.title or link.url, "url": link.url}
            for link in IssueLink.objects.filter(issue_id=issue.id).order_by("created_at")
            if str(link.url or "").startswith(("https://", "http://"))
        ]
        return Response(
            {
                **_post(issue, labels, media),
                "description_html": issue.description_html or "<p></p>",
                "media": _media(project.id, media),
                "links": links,
            }
        )


def _comment(comment, team_ids, user):
    actor = comment.actor
    return {
        "id": str(comment.id),
        "html": comment.comment_html or "",
        "created_at": comment.created_at.isoformat(),
        "author": (actor.display_name or actor.first_name or actor.email.split("@")[0]) if actor else "",
        "avatar_url": actor.avatar_url if actor else None,
        "is_team": bool(actor and actor.id in team_ids),
        "is_mine": bool(actor and actor.id == user.id),
    }


def _text_to_html(text):
    paragraphs = [escape(line) for line in text.replace("\r\n", "\n").split("\n")]
    return "".join(f"<p>{line}</p>" if line else "<p></p>" for line in paragraphs)


class PortalCommentsEndpoint(PortalBaseEndpoint):
    """GET: the post's conversation (external comments only). POST {text}: the client's comment."""

    def _issue(self, request, project_id, issue_id):
        _, project, _, is_client = self.guard(request, project_id)
        issue = visible_issues(project).filter(pk=issue_id).first()
        return project, issue, is_client

    def get(self, request, project_id, issue_id):
        try:
            project, issue, _ = self._issue(request, project_id, issue_id)
        except PortalDenied as exc:
            return _denied(exc)
        if issue is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        team_ids = set(
            ProjectMember.objects.filter(project=project, is_active=True).values_list("member_id", flat=True)
        )
        comments = (
            IssueComment.objects.filter(issue_id=issue.id, project_id=project.id, access="EXTERNAL")
            .select_related("actor")
            .order_by("created_at")[:MAX_COMMENTS]
        )
        return Response({"comments": [_comment(c, team_ids, request.user) for c in comments]})

    def post(self, request, project_id, issue_id):
        try:
            project, issue, is_client = self._issue(request, project_id, issue_id)
        except PortalDenied as exc:
            return _denied(exc)
        if issue is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if not is_client:
            # the team answers from Ops (an external comment), where its notices and history live
            return Response({"error": "Answer from Zil Ops"}, status=status.HTTP_403_FORBIDDEN)
        text = str(request.data.get("text") or "").strip()
        if not text:
            return Response({"error": "Write a comment"}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > MAX_COMMENT:
            return Response({"error": "Comment too long"}, status=status.HTTP_400_BAD_REQUEST)
        comment = IssueComment(
            issue_id=issue.id,
            project_id=project.id,
            workspace_id=project.workspace_id,
            actor=request.user,
            access="EXTERNAL",
            comment_html=_text_to_html(text),
            created_by_id=request.user.id,
        )
        comment.save(created_by_id=request.user.id)
        issue_activity.delay(
            type="comment.activity.created",
            requested_data=json.dumps(
                {"id": str(comment.id), "comment_html": comment.comment_html}, cls=DjangoJSONEncoder
            ),
            actor_id=str(request.user.id),
            issue_id=str(issue.id),
            project_id=str(project.id),
            current_instance=None,
            epoch=int(timezone.now().timestamp()),
        )
        return Response(_comment(comment, set(), request.user), status=status.HTTP_201_CREATED)


class PortalDocumentsEndpoint(PortalBaseEndpoint):
    """GET: the pages the team put in the brand's "Cliente" folder (flat, newest first)."""

    def get(self, request, project_id):
        try:
            portal, _, _, _ = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        pages = folder_pages(portal).order_by("-updated_at")[:MAX_DOCUMENTS]
        return Response(
            {
                "documents": [
                    {"id": str(page.id), "name": page.name or "Sin título", "updated_at": page.updated_at.isoformat()}
                    for page in pages
                ]
            }
        )


class PortalDocumentEndpoint(PortalBaseEndpoint):
    """GET: one page of the "Cliente" folder, read-only."""

    def get(self, request, project_id, page_id):
        try:
            portal, _, _, _ = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        page = folder_pages(portal).filter(pk=page_id).first()
        if page is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "id": str(page.id),
                "name": page.name or "Sin título",
                "updated_at": page.updated_at.isoformat(),
                "description_html": page.description_html or "<p></p>",
            }
        )


class PortalAssetEndpoint(PortalBaseEndpoint):
    """GET: redirect to a file the client may see: a visible post's media or description image, an
    image in an external comment on one, or an image in a page of the "Cliente" folder."""

    def get(self, request, project_id, asset_id):
        try:
            portal, project, _, _ = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        asset = FileAsset.objects.filter(pk=asset_id, project_id=project.id, is_uploaded=True, is_deleted=False).first()
        if asset is None or not self._allowed(asset, portal, project):
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        kind = ((asset.attributes or {}).get("type") or "").split(";")[0].strip().lower()
        disposition = "attachment" if kind in settings.SCRIPT_CAPABLE_MIME_TYPES else "inline"
        url = S3Storage(request=request).generate_presigned_url(object_name=asset.asset.name, disposition=disposition)
        return HttpResponseRedirect(url)

    def _allowed(self, asset, portal, project):
        types = FileAsset.EntityTypeContext
        if asset.entity_type in (types.ISSUE_ATTACHMENT, types.ISSUE_DESCRIPTION):
            return asset.issue_id is not None and visible_issues(project).filter(pk=asset.issue_id).exists()
        if asset.entity_type == types.COMMENT_DESCRIPTION:
            return (
                asset.comment_id is not None
                and IssueComment.objects.filter(
                    Q(pk=asset.comment_id), access="EXTERNAL", issue__in=visible_issues(project)
                ).exists()
            )
        if asset.entity_type == types.PAGE_DESCRIPTION:
            return asset.page_id is not None and folder_pages(portal).filter(pk=asset.page_id).exists()
        return False


class PortalInviteEndpoint(BaseAPIView):
    """The invitation link. GET: who it is for and whether they still have to choose a password.
    POST {password}: chooses it (when they have none yet), spends the link and signs them in."""

    permission_classes = [AllowAny]

    def get(self, request, token):
        client = client_for_token(token)
        if client is None:
            return Response({"error": "invalid"}, status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "email": client.email,
                "brand": client.brand_project.project.name,
                "project_id": str(client.brand_project.project_id),
                "needs_password": needs_password(client.user),
            }
        )

    def post(self, request, token):
        client = client_for_token(token)
        if client is None:
            return Response({"error": "invalid"}, status=status.HTTP_404_NOT_FOUND)
        user = client.user
        project_id = str(client.brand_project.project_id)
        if not needs_password(user):
            # an account with its own password signs in with it: the link only takes them there
            if not use_invite(client):
                return Response({"error": "invalid"}, status=status.HTTP_404_NOT_FOUND)
            return Response({"project_id": project_id, "sign_in": True})
        password = str(request.data.get("password") or "")
        if len(password) < 8 or zxcvbn(password)["score"] < 3:
            return Response({"error": "weak_password"}, status=status.HTTP_400_BAD_REQUEST)
        if not use_invite(client):
            return Response({"error": "invalid"}, status=status.HTTP_404_NOT_FOUND)
        user.set_password(password)
        user.is_password_autoset = False
        fields = ["password", "is_password_autoset", "last_login_time", "last_active", "last_login_medium"]
        now = timezone.now()
        user.last_login_time = now
        user.last_active = now
        user.last_login_medium = "email"
        user.save(update_fields=fields)
        user_login(request=request, user=user, is_space=True)
        return Response({"project_id": project_id})
