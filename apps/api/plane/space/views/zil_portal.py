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
import re
from datetime import date

# Django imports
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect, StreamingHttpResponse
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
from plane.db.models import (
    FileAsset,
    IssueComment,
    IssueLabel,
    IssueLink,
    ProjectMember,
    ZilCommentMoment,
    ZilPageComment,
)
from plane.settings.storage import S3Storage
from plane.utils.zil_client_portal import (
    REVIEW_STATE,
    VISIBLE_LABEL,
    NETWORKS,
    PortalDenied,
    client_brands,
    client_for_token,
    folder_pages,
    folder_tree,
    needs_password,
    notify_page_comment,
    portal_for,
    portal_unit,
    simple_status,
    use_invite,
    visible_issues,
)

from plane.utils.zil_drive import check_link, drive_file_id, drive_media, open_stream, playable

from .base import BaseAPIView

MAX_POSTS = 500
MAX_COMMENTS = 500
MAX_DOCUMENTS = 300
MAX_COMMENT = 5000
MEDIA_TYPES = ("image/", "video/")
MAX_MOMENT = 24 * 60 * 60
STREAM_PIECE = 8 * 1024 * 1024


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
        # Zil's or Meraki's look, by the business unit that works the brand
        "unit": portal_unit(mapping.workspace.slug),
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
            "kind": "file",
        }
        for asset in assets
    ]


def _link_rows(issue):
    """The post's web links, each with who pasted it (kept here: the client never sees emails)."""
    return [
        {
            "title": link.title or link.url,
            "url": link.url,
            "by": (link.created_by.email if link.created_by else "") or "",
            "link": link,
        }
        for link in IssueLink.objects.filter(issue_id=issue.id).select_related("created_by").order_by("created_at")
        if str(link.url or "").startswith(("https://", "http://"))
    ]


def _drive_links(rows):
    """{file_id: row} of the Drive files linked on the post, the first link of each."""
    out = {}
    for row in rows:
        file_id = drive_file_id(row["url"])
        if file_id and file_id not in out:
            out[file_id] = row
    return out


def _drive_url(project_id, issue_id, file_id):
    return f"/api/public/portal/{project_id}/posts/{issue_id}/drive/{file_id}/"


def _post_media(project_id, issue, rows):
    """A post's media: its uploaded images and videos, then the Drive files linked on it, each read
    as the person who pasted the link."""
    media = _media(project_id, _attachments([issue.id]).get(issue.id, []))
    for file_id, row in _drive_links(rows).items():
        media.append(drive_media(file_id, row["title"], row["by"], _drive_url(project_id, issue.id, file_id)))
        # what the client just got, for the team's warning in Ops
        check_link(row["link"])
    return media


def clock(seconds):
    """0:42, 12:05, 1:02:03."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


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
        rows = _link_rows(issue)
        return Response(
            {
                **_post(issue, labels, _attachments([issue.id]).get(issue.id, [])),
                "description_html": issue.description_html or "<p></p>",
                "media": _post_media(project.id, issue, rows),
                # a Drive file is shown as the post's media, not as a link (it may not open for them)
                "links": [{"title": row["title"], "url": row["url"]} for row in rows if not drive_file_id(row["url"])],
            }
        )


def _moment(comment):
    try:
        return comment.zil_moment
    except ZilCommentMoment.DoesNotExist:
        return None


def _comment(comment, team_ids, user):
    actor = comment.actor
    html = comment.comment_html or ""
    moment = _moment(comment)
    if moment and html.startswith(moment.label_html):
        # the portal shows the moment as its own button; Ops reads it from the text
        html = html[len(moment.label_html) :] or "<p></p>"
    return {
        "id": str(comment.id),
        "html": html,
        "moment": ({"media": moment.media, "at": moment.seconds, "label": clock(moment.seconds)} if moment else None),
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
        # the latest ones past the cap, shown oldest first
        latest = (
            IssueComment.objects.filter(issue_id=issue.id, project_id=project.id, access="EXTERNAL")
            .select_related("actor", "zil_moment")
            .order_by("-created_at")[:MAX_COMMENTS]
        )
        return Response({"comments": [_comment(c, team_ids, request.user) for c in reversed(list(latest))]})

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
        # optionally, the second of one of the post's videos it is about
        moment = None
        media_id = str(request.data.get("media") or "")
        if media_id:
            try:
                at = int(request.data.get("at"))
            except (TypeError, ValueError):
                at = -1
            # one the portal plays itself (an unavailable Drive file has no seconds)
            video = next(
                (
                    m
                    for m in _post_media(project.id, issue, _link_rows(issue))
                    if m["id"] == media_id and m["kind"] in ("file", "drive") and m["type"].startswith("video/")
                ),
                None,
            )
            if video is None or not 0 <= at <= MAX_MOMENT:
                return Response({"error": "Unknown moment"}, status=status.HTTP_400_BAD_REQUEST)
            label = f"<p><strong>{clock(at)}</strong> · {escape(video['name'] or media_id)}</p>"
            moment = {"media": media_id, "seconds": at, "label_html": label}
        comment = IssueComment(
            issue_id=issue.id,
            project_id=project.id,
            workspace_id=project.workspace_id,
            actor=request.user,
            access="EXTERNAL",
            comment_html=(moment["label_html"] if moment else "") + _text_to_html(text),
            created_by_id=request.user.id,
        )
        with transaction.atomic():
            comment.save(created_by_id=request.user.id)
            if moment:
                ZilCommentMoment.objects.create(comment=comment, created_by_id=request.user.id, **moment)
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
    """GET: what the team put in the brand's "Cliente" folder: its sub-folders and pages, each with its
    parent (the folder itself is the root), so the portal shows the same tree."""

    def get(self, request, project_id):
        try:
            portal, _, _, _ = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        folders, pages = folder_tree(portal)
        root = str(portal.pages_folder_id)

        def parent_of(page):
            return None if str(page.parent_id) == root else str(page.parent_id)

        return Response(
            {
                "folders": [
                    {"id": str(f.id), "name": f.name or "", "parent_id": parent_of(f)}
                    for f in folders.order_by("sort_order", "name")[:MAX_DOCUMENTS]
                ],
                "documents": [
                    {
                        "id": str(page.id),
                        "name": page.name or "",
                        "updated_at": page.updated_at.isoformat(),
                        "parent_id": parent_of(page),
                    }
                    for page in pages.order_by("-updated_at")[:MAX_DOCUMENTS]
                ],
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
                "name": page.name or "",
                "updated_at": page.updated_at.isoformat(),
                "description_html": page.description_html or "<p></p>",
            }
        )


def _page_comment(comment, team_ids, user):
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


class PortalDocumentCommentsEndpoint(PortalBaseEndpoint):
    """GET: the conversation on a document of the "Cliente" folder. POST {text}: the client's comment."""

    def _page(self, request, project_id, page_id):
        portal, project, _, is_client = self.guard(request, project_id)
        return project, folder_pages(portal).filter(pk=page_id).first(), is_client

    def get(self, request, project_id, page_id):
        try:
            project, page, _ = self._page(request, project_id, page_id)
        except PortalDenied as exc:
            return _denied(exc)
        if page is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        team_ids = set(
            ProjectMember.objects.filter(project=project, is_active=True).values_list("member_id", flat=True)
        )
        latest = ZilPageComment.objects.filter(page=page).select_related("actor").order_by("-created_at")[:MAX_COMMENTS]
        return Response({"comments": [_page_comment(c, team_ids, request.user) for c in reversed(list(latest))]})

    def post(self, request, project_id, page_id):
        try:
            project, page, is_client = self._page(request, project_id, page_id)
        except PortalDenied as exc:
            return _denied(exc)
        if page is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if not is_client:
            return Response({"error": "Answer from Zil Ops"}, status=status.HTTP_403_FORBIDDEN)
        text = str(request.data.get("text") or "").strip()
        if not text:
            return Response({"error": "Write a comment"}, status=status.HTTP_400_BAD_REQUEST)
        if len(text) > MAX_COMMENT:
            return Response({"error": "Comment too long"}, status=status.HTTP_400_BAD_REQUEST)
        comment = ZilPageComment(
            page=page,
            project_id=project.id,
            workspace_id=project.workspace_id,
            actor=request.user,
            comment_html=_text_to_html(text),
        )
        comment.save(created_by_id=request.user.id)
        notify_page_comment(page, comment, request.user)
        return Response(_page_comment(comment, set(), request.user), status=status.HTTP_201_CREATED)


class PortalDriveStreamEndpoint(PortalBaseEndpoint):
    """GET: the bytes of a Drive video (or image) linked on a visible post, read as whoever pasted
    the link, in pieces (HTTP Range) so the player can jump to any second. Nothing else of Drive
    goes through here: a file not linked on this post is a 404."""

    def get(self, request, project_id, issue_id, file_id):
        try:
            _, project, _, _ = self.guard(request, project_id)
        except PortalDenied as exc:
            return _denied(exc)
        issue = visible_issues(project).filter(pk=issue_id).first()
        row = _drive_links(_link_rows(issue)).get(file_id) if issue else None
        meta = playable(file_id, row["by"]) if row else None
        if meta is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        upstream = open_stream(file_id, row["by"], _bounded_range(request.headers.get("Range")))
        if upstream is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        def chunks():
            try:
                yield from upstream.iter_content(chunk_size=64 * 1024)
            finally:
                upstream.close()

        response = StreamingHttpResponse(chunks(), status=upstream.status_code, content_type=meta["mimeType"])
        for header in ("Content-Length", "Content-Range"):
            if upstream.headers.get(header):
                response[header] = upstream.headers[header]
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        return response


def _bounded_range(raw):
    """The player's Range, at most STREAM_PIECE bytes at a time: a request never holds a worker for a
    whole video (the player asks for the next piece). The first request gets the first piece."""
    match = re.fullmatch(r"bytes=(\d+)-(\d*)", str(raw or "").strip())
    start = int(match.group(1)) if match else 0
    end = start + STREAM_PIECE - 1
    if match and match.group(2):
        end = min(end, int(match.group(2)))
    return f"bytes={start}-{end}"


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
                "unit": portal_unit(client.brand_project.workspace.slug),
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
