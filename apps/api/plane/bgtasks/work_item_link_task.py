# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Python imports
import logging
import socket

# Third party imports
from celery import shared_task
import requests
from bs4 import BeautifulSoup
from django.utils import timezone
from urllib.parse import urlparse, urljoin, quote
import base64
import ipaddress
from typing import Dict, Any, Tuple
from typing import Optional
from plane.db.models import IssueLink
from plane.utils.exception_logger import log_exception
from plane.utils.ip_address import is_blocked_ip
from plane.utils.url_security import pinned_fetch, pinned_fetch_following_redirects

logger = logging.getLogger("plane.worker")


DEFAULT_FAVICON = "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9ImN1cnJlbnRDb2xvciIgc3Ryb2tlLXdpZHRoPSIyIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiIGNsYXNzPSJsdWNpZGUgbHVjaWRlLWxpbmstaWNvbiBsdWNpZGUtbGluayI+PHBhdGggZD0iTTEwIDEzYTUgNSAwIDAgMCA3LjU0LjU0bDMtM2E1IDUgMCAwIDAtNy4wNy03LjA3bC0xLjcyIDEuNzEiLz48cGF0aCBkPSJNMTQgMTFhNSA1IDAgMCAwLTcuNTQtLjU0bC0zIDNhNSA1IDAgMCAwIDcuMDcgNy4wN2wxLjcxLTEuNzEiLz48L3N2Zz4="  # noqa: E501

# Domain-specific "rich" providers we fetch extra metadata for, on top of the
# generic title/favicon crawl. Kept to public, no-OAuth endpoints only.
PROVIDER_FIGMA = "figma"
PROVIDER_GOOGLE_DRIVE = "google_drive"

FIGMA_OEMBED_ENDPOINT = "https://www.figma.com/api/oembed"
GOOGLE_DRIVE_HOSTNAMES = {"drive.google.com", "docs.google.com"}

# Provider-specific calls get a slightly longer budget than the 1s default
# used for the generic favicon/title crawl, but stay tightly bounded so a
# slow/unresponsive provider never stalls the worker.
PROVIDER_METADATA_TIMEOUT = 3


def validate_url_ip(url: str) -> None:
    """
    Validate that a URL doesn't point to a private/internal IP address.
    Resolves hostnames to IPs before checking.

    Args:
        url: The URL to validate

    Raises:
        ValueError: If the URL points to a private/internal IP
    """
    parsed = urlparse(url)

    # Only allow HTTP and HTTPS to prevent file://, gopher://, etc.
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Invalid URL scheme. Only HTTP and HTTPS are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL: No hostname found")

    # Resolve hostname to IP addresses — this catches domain names that
    # point to internal IPs (e.g. attacker.com -> 169.254.169.254)

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, UnicodeError):
        # UnicodeError covers IDNA failures raised before the address lookup.
        raise ValueError("Hostname could not be resolved")

    if not addr_info:
        raise ValueError("No IP addresses found for the hostname")

    # Check every resolved IP against blocked ranges to prevent SSRF. The
    # actual fetch is pinned to the validated IP (see safe_get), so this acts
    # as an early, fail-closed pre-filter.
    for addr in addr_info:
        ip = ipaddress.ip_address(addr[4][0].split("%")[0])
        if is_blocked_ip(ip):
            raise ValueError("Access to private/internal networks is not allowed")


MAX_REDIRECTS = 5


def safe_get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 1,
) -> Tuple[requests.Response, str]:
    """
    Perform a GET request that resolves, validates and pins every hop to its
    validated IP. Prevents SSRF via private/internal targets, DNS rebinding
    (TOCTOU) and redirects that bounce to internal addresses.

    Args:
        url: The URL to fetch
        headers: Optional request headers
        timeout: Request timeout in seconds

    Returns:
        A tuple of (final Response object, final URL after redirects)

    Raises:
        ValueError: If any URL in the redirect chain points to a private IP
        requests.RequestException: On network errors (incl. TooManyRedirects)
    """
    return pinned_fetch_following_redirects(
        "GET",
        url,
        headers=headers,
        timeout=timeout,
        max_redirects=MAX_REDIRECTS,
    )


def crawl_work_item_link_title_and_favicon(url: str) -> Dict[str, Any]:
    """
    Crawls a URL to extract the title and favicon.

    Args:
        url (str): The URL to crawl

    Returns:
        str: JSON string containing title and base64-encoded favicon
    """
    try:
        # Set up headers to mimic a real browser
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"  # noqa: E501
        }

        soup = None
        title = None
        final_url = url

        try:
            response, final_url = safe_get(url, headers=headers)

            soup = BeautifulSoup(response.content, "html.parser")
            title_tag = soup.find("title")
            title = title_tag.get_text().strip() if title_tag else None

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch HTML for title: {str(e)}")
        except (ValueError, RuntimeError) as e:
            logger.warning(f"URL validation failed: {str(e)}")

        # Fetch and encode favicon using final URL (after redirects) for correct relative href resolution
        favicon_base64 = fetch_and_encode_favicon(headers, soup, final_url)

        # Prepare result
        result = {
            "title": title,
            "favicon": favicon_base64["favicon_base64"],
            "url": url,
            "favicon_url": favicon_base64["favicon_url"],
        }

        return result

    except Exception as e:
        log_exception(e)
        return {
            "error": f"Unexpected error: {str(e)}",
            "title": None,
            "favicon": None,
            "url": url,
        }


def find_favicon_url(soup: Optional[BeautifulSoup], base_url: str) -> Optional[str]:
    """
    Find the favicon URL from HTML soup.

    Args:
        soup: BeautifulSoup object
        base_url: Base URL for resolving relative paths

    Returns:
        str: Absolute URL to favicon or None
    """

    if soup is not None:
        # Look for various favicon link tags
        favicon_selectors = [
            'link[rel="icon"]',
            'link[rel="shortcut icon"]',
            'link[rel="apple-touch-icon"]',
            'link[rel="apple-touch-icon-precomposed"]',
        ]

        for selector in favicon_selectors:
            favicon_tag = soup.select_one(selector)
            if favicon_tag and favicon_tag.get("href"):
                favicon_href = urljoin(base_url, favicon_tag["href"])
                validate_url_ip(favicon_href)
                return favicon_href

    # Fallback to /favicon.ico
    parsed_url = urlparse(base_url)
    fallback_url = f"{parsed_url.scheme}://{parsed_url.netloc}/favicon.ico"

    # Check if fallback exists (pinned to the validated IP).
    try:
        response = pinned_fetch("HEAD", fallback_url, timeout=2)

        if response.status_code == 200:
            return fallback_url
    except (requests.RequestException, ValueError) as e:
        log_exception(e, warning=True)
        return None

    return None


def fetch_and_encode_favicon(
    headers: Dict[str, str], soup: Optional[BeautifulSoup], url: str
) -> Dict[str, Optional[str]]:
    """
    Fetch favicon and encode it as base64.

    Args:
        favicon_url: URL to the favicon
        headers: Request headers

    Returns:
        str: Base64 encoded favicon with data URI prefix or None
    """
    try:
        favicon_url = find_favicon_url(soup, url)
        if favicon_url is None:
            return {
                "favicon_url": None,
                "favicon_base64": f"data:image/svg+xml;base64,{DEFAULT_FAVICON}",
            }

        response, _ = safe_get(favicon_url, headers=headers)

        # Get content type
        content_type = response.headers.get("content-type", "image/x-icon")

        # Convert to base64
        favicon_base64 = base64.b64encode(response.content).decode("utf-8")

        # Return as data URI
        return {
            "favicon_url": favicon_url,
            "favicon_base64": f"data:{content_type};base64,{favicon_base64}",
        }

    except Exception as e:
        logger.warning(f"Failed to fetch favicon: {e}")
        return {
            "favicon_url": None,
            "favicon_base64": f"data:image/svg+xml;base64,{DEFAULT_FAVICON}",
        }


def get_link_provider(url: str) -> Optional[str]:
    """
    Identify a link as belonging to a known "rich" provider based on its
    hostname, so the crawler can branch to a provider-specific fetch.

    Returns:
        str: One of the PROVIDER_* constants, or None for a generic link.
    """
    try:
        hostname = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None

    if hostname == "figma.com" or hostname.endswith(".figma.com"):
        return PROVIDER_FIGMA
    if hostname in GOOGLE_DRIVE_HOSTNAMES:
        return PROVIDER_GOOGLE_DRIVE
    return None


def extract_og_metadata(soup: Optional[BeautifulSoup]) -> Dict[str, Optional[str]]:
    """
    Extract Open Graph title/image from HTML soup, if present.
    """
    og_title = None
    og_image = None

    if soup is not None:
        title_tag = soup.find("meta", attrs={"property": "og:title"})
        image_tag = soup.find("meta", attrs={"property": "og:image"})
        if title_tag and title_tag.get("content"):
            og_title = title_tag["content"].strip()
        if image_tag and image_tag.get("content"):
            og_image = image_tag["content"].strip()

    return {"og_title": og_title, "og_image": og_image}


def crawl_figma_link_metadata(url: str) -> Dict[str, Any]:
    """
    Crawls provider metadata for a Figma link via Figma's public, no-auth
    oEmbed endpoint (https://www.figma.com/api/oembed), on top of the
    standard title/favicon crawl. Never raises — falls back to the generic
    result (tagged with the provider) if the oEmbed call fails, e.g. because
    the file isn't publicly shared.
    """
    result = crawl_work_item_link_title_and_favicon(url)
    result["provider"] = PROVIDER_FIGMA
    result["provider_name"] = "Figma"
    result["crawled_at"] = timezone.now().isoformat()

    try:
        oembed_url = f"{FIGMA_OEMBED_ENDPOINT}?url={quote(url, safe='')}"
        response, _ = safe_get(oembed_url, timeout=PROVIDER_METADATA_TIMEOUT)
        data = response.json()

        if data.get("title"):
            result["title"] = data["title"]
        if data.get("thumbnail_url"):
            result["thumbnail"] = data["thumbnail_url"]
        if data.get("provider_name"):
            result["provider_name"] = data["provider_name"]
        if data.get("author_name"):
            result["author_name"] = data["author_name"]
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"Failed to fetch Figma oEmbed metadata for {url}: {e}")
    except Exception as e:
        log_exception(e, warning=True)

    return result


def crawl_google_drive_link_metadata(url: str) -> Dict[str, Any]:
    """
    Crawls provider metadata for a Google Drive share link using the Open
    Graph tags (og:title / og:image) Google renders on the public share
    page, on top of the standard title/favicon crawl. Never raises — falls
    back to the generic result (tagged with the provider) if the page can't
    be fetched or has no OG tags, e.g. because the file isn't shared publicly.
    """
    result = crawl_work_item_link_title_and_favicon(url)
    result["provider"] = PROVIDER_GOOGLE_DRIVE
    result["provider_name"] = "Google Drive"
    result["crawled_at"] = timezone.now().isoformat()

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"  # noqa: E501
        }
        response, _ = safe_get(url, headers=headers, timeout=PROVIDER_METADATA_TIMEOUT)
        soup = BeautifulSoup(response.content, "html.parser")
        og_meta = extract_og_metadata(soup)

        if og_meta["og_title"]:
            result["title"] = og_meta["og_title"]
        if og_meta["og_image"]:
            result["thumbnail"] = og_meta["og_image"]
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"Failed to fetch Google Drive metadata for {url}: {e}")
    except Exception as e:
        log_exception(e, warning=True)

    return result


@shared_task
def crawl_work_item_link_title(id: str, url: str) -> None:
    provider = get_link_provider(url)

    if provider == PROVIDER_FIGMA:
        meta_data = crawl_figma_link_metadata(url)
    elif provider == PROVIDER_GOOGLE_DRIVE:
        meta_data = crawl_google_drive_link_metadata(url)
    else:
        meta_data = crawl_work_item_link_title_and_favicon(url)

    try:
        issue_link = IssueLink.objects.get(id=id)
    except IssueLink.DoesNotExist:
        logger.warning(f"IssueLink not found for the id {id} and the url {url}")
        return

    issue_link.metadata = meta_data
    issue_link.save()
