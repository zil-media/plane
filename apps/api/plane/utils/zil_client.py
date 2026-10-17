# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Read-only client for Zil Workspace clients (MgmtClient), used to link folders.

Zil is the source of truth for clients; Plane only searches them and caches
display fields on PageZilClientLink. Requires ZIL_BASE_URL + ZIL_SERVICE_SECRET.
"""

# Python imports
import os
import re

# Third party imports
import requests

# Django imports
from django.utils import timezone

# Module imports
from plane.utils.exception_logger import log_exception

OBJECT_ID_RE = re.compile(r"^[a-f0-9]{24}$")
ZIL_TIMEOUT_SECONDS = 4
DRAFT_REVIEW_TIMEOUT_SECONDS = 16


class ZilUnavailable(Exception):
    pass


def apply_zil_client_fields(link, client):
    """Copy Zil's client DTO into a PageZilClientLink's cached display fields."""
    link.alias = (client.get("alias") or "")[:255]
    link.company_name = (client.get("companyName") or "")[:255]
    link.lifecycle_status = (client.get("lifecycleStatus") or "")[:32]
    link.business_unit_slug = (client.get("businessUnitSlug") or "")[:64]
    link.synced_at = timezone.now()


def zil_enabled():
    return bool(os.environ.get("ZIL_BASE_URL") and os.environ.get("ZIL_SERVICE_SECRET"))


def is_valid_client_id(client_id):
    return bool(client_id) and bool(OBJECT_ID_RE.match(str(client_id)))


def _get(path, params):
    base = os.environ.get("ZIL_BASE_URL", "").rstrip("/")
    secret = os.environ.get("ZIL_SERVICE_SECRET", "")
    try:
        return requests.get(
            f"{base}{path}",
            params=params,
            headers={"X-Zil-Service-Key": secret},
            timeout=ZIL_TIMEOUT_SECONDS,
        )
    except Exception as e:
        log_exception(e)
        raise ZilUnavailable() from e


def _post(path, payload, timeout=ZIL_TIMEOUT_SECONDS * 2):
    base = os.environ.get("ZIL_BASE_URL", "").rstrip("/")
    secret = os.environ.get("ZIL_SERVICE_SECRET", "")
    try:
        return requests.post(
            f"{base}{path}",
            json=payload,
            headers={"X-Zil-Service-Key": secret},
            timeout=timeout,
        )
    except Exception as e:
        log_exception(e)
        raise ZilUnavailable() from e


def search_zil_clients(workspace_slug, q="", limit=20, actor_email=None):
    """Active clients of the Business Units mapped to this workspace, each with its active brands.

    With `actor_email`, only the ones that person can pick (Zil decides: a director or finance
    sees them all, anyone else the clients of the projects they are assigned to). Raises ZilUnavailable.
    """
    params = {"workspaceSlug": workspace_slug, "q": q[:100], "limit": limit}
    if actor_email:
        params["actor"] = actor_email
    resp = _get("/api/sso/clients", params)
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        return resp.json().get("clients") or []
    except ValueError as e:
        raise ZilUnavailable() from e


def get_zil_client(workspace_slug, client_id):
    """A single client, or None when it doesn't exist or belongs to another workspace's BUs."""
    if not is_valid_client_id(client_id):
        return None
    resp = _get(f"/api/sso/clients/{client_id}", {"workspaceSlug": workspace_slug})
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        return resp.json().get("client")
    except ValueError as e:
        raise ZilUnavailable() from e


def search_zil_projects(workspace_slug, q="", limit=20, actor_email=None, client_id=None, brand_id=None):
    """Active projects (TimeProject) of the Business Units mapped to this workspace. Raises ZilUnavailable.

    `actor_email` keeps the ones that person can pick; `client_id` / `brand_id` the ones of that
    client (and of that brand or without one), so a work item's Proyecto matches its Cliente.
    """
    params = {"workspaceSlug": workspace_slug, "q": q[:100], "limit": limit}
    for key, value in (("actor", actor_email), ("clientId", client_id), ("brandId", brand_id)):
        if value:
            params[key] = value
    resp = _get("/api/sso/projects", params)
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        return resp.json().get("projects") or []
    except ValueError as e:
        raise ZilUnavailable() from e


def get_issue_erp_refs(workspace_slug, issue_id):
    """The ERP client/project whose planeLinks[] point at this work item: {client, project}."""
    resp = _get("/api/zil/issue-refs", {"workspace_slug": workspace_slug, "plane_issue_id": issue_id})
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        data = resp.json()
    except ValueError as e:
        raise ZilUnavailable() from e
    return {"client": data.get("client"), "project": data.get("project")}


def set_issue_erp_ref(payload):
    """Ask Zil to (re)link or unlink a work item to a client/project; Zil owns the link.

    Returns the new {client, project}, or None when the ERP entity doesn't belong to the
    workspace (404). Raises ZilUnavailable otherwise.
    """
    resp = _post("/api/zil/issue-refs", payload)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        data = resp.json()
    except ValueError as e:
        raise ZilUnavailable() from e
    return {"client": data.get("client"), "project": data.get("project")}


def file_workspace_bug(payload):
    """File in Zil Workspace a bug whose cause the Ops fixer traced there: {id, trackingUrl}.

    Idempotent on payload["opsBugId"] (a retry returns the report already filed). Raises
    ZilUnavailable when Zil doesn't take it.
    """
    resp = _post("/api/zil/bug-reports", payload)
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        data = resp.json()
    except ValueError as e:
        raise ZilUnavailable() from e
    if not data.get("id"):
        raise ZilUnavailable()
    return {"id": data["id"], "tracking_url": data.get("trackingUrl") or ""}


def review_draft(kind, title, text, screen):
    """Zil Workspace's draft reviewer, for the support forms: {ready, questions}, or None.

    Never raises. The review is a hint over a draft the person already wrote: Zil being down or
    answering something unexpected means no review panel, never a broken form (the same contract
    the reviewer has inside Workspace).
    """
    try:
        # Workspace gives the model up to 15s: giving up sooner throws away a review already paid for.
        resp = _post(
            "/api/zil/draft-review",
            {"kind": kind, "title": title, "text": text, "screen": screen},
            timeout=DRAFT_REVIEW_TIMEOUT_SECONDS,
        )
    except ZilUnavailable:
        return None
    if resp.status_code != 200:
        return None
    try:
        review = resp.json().get("review")
    except ValueError:
        return None
    if not isinstance(review, dict) or not isinstance(review.get("ready"), bool):
        return None
    questions = review.get("questions")
    return {"ready": review["ready"], "questions": questions if isinstance(questions, list) else []}


# ERP entity types that keep a document array a Plane attachment can be saved into.
ZIL_DOC_TARGET_TYPES = ("Lead", "MgmtClient")


def get_issue_erp_doc_targets(issue_id):
    """The ERP records linked to this work item that can hold documents: [{type, id, name}]."""
    resp = _get("/api/zil/entity-meta", {"plane_entity_id": issue_id})
    if resp.status_code == 404:
        return []
    if resp.status_code != 200:
        raise ZilUnavailable()
    try:
        links = resp.json().get("links") or []
    except ValueError as e:
        raise ZilUnavailable() from e
    return [
        {"type": link["type"], "id": link["id"], "name": link.get("name") or ""}
        for link in links
        if link.get("type") in ZIL_DOC_TARGET_TYPES and link.get("id")
    ]


def save_issue_doc_to_zil(payload):
    """Ask Zil to copy a work item attachment into a linked Lead/MgmtClient's documents.

    Returns True, or None when that ERP entity isn't linked to the work item (404).
    Raises ZilUnavailable otherwise.
    """
    resp = _post("/api/zil/plane-doc", payload)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise ZilUnavailable()
    return True


ZIL_RELAY_TIMEOUT_SECONDS = 15


def zil_client_relay(method, client_id, subpath, workspace_slug, actor_email, json=None, files=None):
    """Relay a client-profile call (profile, assets, brand files) to Zil as `actor_email`.

    Zil re-checks the actor's access to the workspace and the client's scope, so Plane only
    forwards. Returns (status_code, body dict). Raises ZilUnavailable when Zil can't be reached.
    """
    base = os.environ.get("ZIL_BASE_URL", "").rstrip("/")
    secret = os.environ.get("ZIL_SERVICE_SECRET", "")
    try:
        resp = requests.request(
            method,
            f"{base}/api/sso/clients/{client_id}{subpath}",
            params={"workspaceSlug": workspace_slug, "actor": actor_email},
            json=json,
            files=files,
            headers={"X-Zil-Service-Key": secret},
            timeout=ZIL_RELAY_TIMEOUT_SECONDS,
        )
    except Exception as e:
        log_exception(e)
        raise ZilUnavailable() from e
    if resp.status_code >= 500:
        raise ZilUnavailable()
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return resp.status_code, body
