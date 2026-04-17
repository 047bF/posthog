"""Self-serve partner registration for the agentic provisioning API."""

from __future__ import annotations

import socket
import secrets
import ipaddress
from typing import Any
from urllib.parse import urlparse

from django.core.cache import cache

import structlog
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.models.oauth import OAuthApplication
from posthog.rate_limit import PartnerRegistrationIPThrottle

logger = structlog.get_logger(__name__)

VALID_AUTH_METHODS = {"hmac", "bearer", "pkce"}

PARTNER_RATE_LIMIT_CACHE_PREFIX = "provisioning_partner_rate:"
DEFAULT_PARTNER_RATE_LIMIT_ACCOUNT_REQUESTS = 100
DEFAULT_PARTNER_RATE_LIMIT_TOKEN_EXCHANGES = 200
DEFAULT_PARTNER_RATE_LIMIT_RESOURCE_CREATES = 100
PARTNER_RATE_LIMIT_WINDOW_SECONDS = 3600


def _is_private_ip(hostname: str) -> bool:
    try:
        addr = ipaddress.ip_address(hostname)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        return False


def _validate_callback_url(url: str) -> str | None:
    """Validate a callback URL for SSRF safety. Returns an error message or None if valid."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    if not parsed.scheme or not parsed.netloc:
        return "URL must include scheme and host"

    blocked_schemes = OAuthApplication.DEFAULT_BLOCKED_SCHEMES
    if parsed.scheme in blocked_schemes:
        return f"URL scheme '{parsed.scheme}' is not allowed"

    is_loopback = parsed.hostname in ("localhost", "127.0.0.1", "::1", "[::1]")
    if not is_loopback and parsed.scheme != "https":
        return "Only https:// URLs are allowed (except localhost for development)"

    if parsed.hostname and not is_loopback and _is_private_ip(str(parsed.hostname)):
        return "Callback URL must not point to a private/internal IP address"

    if parsed.hostname and not is_loopback:
        try:
            resolved = socket.getaddrinfo(parsed.hostname, None)
            for _, _, _, _, sockaddr in resolved:
                ip_str = str(sockaddr[0])
                if _is_private_ip(ip_str):
                    return "Callback URL resolves to a private/internal IP address"
        except socket.gaierror:
            pass

    return None


def check_partner_rate_limit(partner: OAuthApplication, endpoint: str, limit: int | None) -> Response | None:
    if limit is None:
        return None

    cache_key = f"{PARTNER_RATE_LIMIT_CACHE_PREFIX}{partner.id}:{endpoint}"
    current = cache.get(cache_key, 0)
    if current >= limit:
        logger.warning(
            "agentic_provisioning.partner_rate_limited",
            partner_id=str(partner.id),
            endpoint=endpoint,
            limit=limit,
        )
        return Response(
            {
                "type": "error",
                "error": {"code": "rate_limited", "message": f"Rate limit exceeded for {endpoint}"},
            },
            status=429,
        )
    cache.set(cache_key, current + 1, PARTNER_RATE_LIMIT_WINDOW_SECONDS)
    return None


def _capture_registration_event(outcome: str, **extra: object) -> None:
    import uuid

    import posthoganalytics

    posthoganalytics.capture(
        f"agentic_provisioning partner_registered",
        distinct_id=f"agentic_provisioning_{uuid.uuid4().hex[:16]}",
        properties={"outcome": outcome, **extra},
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([])
@throttle_classes([PartnerRegistrationIPThrottle])
def provisioning_register(request: Request) -> Response:
    data = request.data
    name = data.get("name", "").strip()
    callback_url = data.get("callback_url", "").strip()
    auth_method = data.get("auth_method", "").strip()
    partner_type = data.get("partner_type", "").strip()
    logo_uri = data.get("logo_uri", "").strip() or None

    if not name:
        return Response({"error": "name is required"}, status=400)
    if not callback_url:
        return Response({"error": "callback_url is required"}, status=400)
    if not auth_method:
        return Response({"error": "auth_method is required"}, status=400)
    if auth_method not in VALID_AUTH_METHODS:
        return Response({"error": f"auth_method must be one of: {', '.join(sorted(VALID_AUTH_METHODS))}"}, status=400)

    url_error = _validate_callback_url(callback_url)
    if url_error:
        return Response({"error": f"Invalid callback_url: {url_error}"}, status=400)

    from oauthlib.common import generate_token

    client_id = generate_token()
    client_secret = generate_token() if auth_method in ("hmac", "bearer") else ""

    signing_secret = ""
    if auth_method == "hmac":
        signing_secret = secrets.token_hex(32)

    client_type = OAuthApplication.CLIENT_PUBLIC if auth_method == "pkce" else OAuthApplication.CLIENT_CONFIDENTIAL

    try:
        app = OAuthApplication.objects.create(
            name=name,
            client_id=client_id,
            client_secret=client_secret,
            client_type=client_type,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris=callback_url,
            algorithm="RS256",
            logo_uri=logo_uri,
            provisioning_auth_method=auth_method,
            provisioning_signing_secret=signing_secret or "",
            provisioning_partner_type=partner_type,
            provisioning_active=False,
            provisioning_can_create_accounts=False,
            provisioning_can_provision_resources=True,
        )
    except Exception as e:
        capture_exception(e)
        return Response({"error": "Failed to create partner application"}, status=500)

    _capture_registration_event(
        "success",
        partner_type=partner_type,
        auth_method=auth_method,
        app_id=str(app.id),
    )

    response_data: dict[str, Any] = {
        "client_id": client_id,
        "name": name,
        "auth_method": auth_method,
        "provisioning_active": False,
        "message": "Partner registered successfully. An admin must activate provisioning before you can use the API.",
    }

    if auth_method in ("hmac", "bearer"):
        response_data["client_secret"] = client_secret

    if auth_method == "hmac":
        response_data["signing_secret"] = signing_secret

    return Response(response_data, status=201)
