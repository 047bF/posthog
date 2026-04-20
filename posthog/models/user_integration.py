import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import models

import requests
import structlog

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.utils import UUIDModel

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from posthog.models.user import User

# GitHub rejects a refresh token with one of these error codes when it's
# no longer valid; the user must re-authorize through the install flow.
_GITHUB_UNRECOVERABLE_REFRESH_ERRORS = frozenset(
    {
        "bad_refresh_token",
        "incorrect_client_credentials",
        "refresh_token_expired",
        "unauthorized_client",
    }
)


class UserIntegration(UUIDModel):
    """User-scoped integration with an external service.

    Unlike team-level ``Integration`` (which gives the whole project access
    to repos), a ``UserIntegration`` tracks a single user's own connection —
    their own GitHub App installation plus user-to-server tokens for acting
    as them.

    For GitHub:
    - ``integration_id`` holds the GitHub App installation_id
    - ``config`` holds installation metadata + user identity (login, id)
    - ``sensitive_config`` holds installation access token + user-to-server tokens
    """

    class IntegrationKind(models.TextChoices):
        GITHUB = "github"

    user = models.ForeignKey(
        "posthog.User",
        on_delete=models.CASCADE,
        related_name="integrations",
    )
    kind = models.CharField(max_length=32, choices=IntegrationKind.choices)
    # External system ID (GitHub installation_id)
    integration_id = models.TextField(null=True, blank=True)
    config = models.JSONField(default=dict)
    sensitive_config = EncryptedJSONField(default=dict, ignore_decrypt_errors=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_user_integration"
        unique_together = [("user", "kind")]


class ReauthorizationRequired(Exception):
    """The stored GitHub tokens cannot produce a usable access token; user must re-authorize."""


class UserGitHubIntegration:
    """Helper for operating on a GitHub ``UserIntegration``.

    Manages two token types:

    - **Installation access token** (``sensitive_config["access_token"]``):
      app-level token for repo operations (listing repos, checking access).
      Refreshed via the GitHub App JWT, same as team-level ``GitHubIntegration``.

    - **User-to-server token** (``sensitive_config["user_access_token"]``):
      acts as the user in repos covered by the installation. Used for creating
      PRs, commits, etc. Refreshed via the OAuth refresh-token flow.

    ``config`` layout::

        {
            "installation_id": "12345",
            "expires_in": 3600,              # installation token TTL
            "refreshed_at": <unix>,          # installation token refresh time
            "repository_selection": "selected",
            "account": {"type": "User", "name": "octocat"},
            "github_user": {"login": "octocat", "id": 123},
            "user_token_refreshed_at": <unix>,
            "user_access_token_expires_at": <unix>,
            "user_refresh_token_expires_at": <unix>,
        }

    ``sensitive_config`` layout::

        {
            "access_token": "<installation token>",
            "user_access_token": "<user-to-server token>",
            "user_refresh_token": "<user-to-server refresh token>",
        }
    """

    integration: UserIntegration

    def __init__(self, integration: UserIntegration) -> None:
        if integration.kind != "github":
            raise Exception("UserGitHubIntegration initialized with non-github integration")
        self.integration = integration

    # --- Identity ---

    @property
    def github_login(self) -> str | None:
        github_user = self.integration.config.get("github_user")
        if isinstance(github_user, dict):
            login = github_user.get("login")
            return str(login) if login else None
        return None

    @property
    def github_id(self) -> int | None:
        github_user = self.integration.config.get("github_user")
        if isinstance(github_user, dict):
            gh_id = github_user.get("id")
            return int(gh_id) if gh_id is not None else None
        return None

    # --- Installation access token (app-level) ---

    @property
    def installation_access_token(self) -> str | None:
        return self.integration.sensitive_config.get("access_token") if self.integration.sensitive_config else None

    def installation_access_token_expired(self) -> bool:
        expires_in = self.integration.config.get("expires_in")
        refreshed_at = self.integration.config.get("refreshed_at")
        if not expires_in or not refreshed_at:
            return False
        time_threshold = max(1, int(expires_in / 2))
        return time.time() > refreshed_at + expires_in - time_threshold

    def refresh_installation_access_token(self) -> None:
        """Refresh the installation access token using the GitHub App JWT."""
        from posthog.models.integration import GitHubIntegration as TeamGitHubIntegration

        installation_id = self.integration.integration_id
        if not installation_id:
            raise Exception("No installation_id on UserIntegration, cannot refresh")

        response = TeamGitHubIntegration.client_request(f"installations/{installation_id}/access_tokens", method="POST")
        data = response.json()

        if response.status_code != 201 or not data.get("token"):
            raise Exception(f"Failed to refresh installation token: {response.text}")

        expires_in = datetime.fromisoformat(data["expires_at"]).timestamp() - int(time.time())
        self.integration.config = {
            **self.integration.config,
            "expires_in": expires_in,
            "refreshed_at": int(time.time()),
        }
        self.integration.sensitive_config = {
            **(self.integration.sensitive_config or {}),
            "access_token": data["token"],
        }
        self.integration.save(update_fields=["config", "sensitive_config", "updated_at"])

    # --- User-to-server token ---

    @property
    def user_access_token(self) -> str | None:
        return self.integration.sensitive_config.get("user_access_token") if self.integration.sensitive_config else None

    @property
    def user_refresh_token(self) -> str | None:
        return (
            self.integration.sensitive_config.get("user_refresh_token") if self.integration.sensitive_config else None
        )

    def user_access_token_expired(self) -> bool:
        expires_at = self.integration.config.get("user_access_token_expires_at")
        if not expires_at:
            return False
        refreshed_at = self.integration.config.get("user_token_refreshed_at") or self.integration.created_at.timestamp()
        threshold = max(1, int((expires_at - refreshed_at) // 2))
        return time.time() > expires_at - threshold

    def user_refresh_token_expired(self) -> bool:
        expires_at = self.integration.config.get("user_refresh_token_expires_at")
        if not expires_at:
            return False
        return time.time() > expires_at

    def refresh_user_access_token(self) -> None:
        """Exchange the refresh token for a fresh user-to-server access token.

        Deletes the integration row and raises :class:`ReauthorizationRequired`
        when GitHub signals the refresh token can't produce a new access token.
        """
        client_id = settings.GITHUB_APP_CLIENT_ID
        client_secret = settings.GITHUB_APP_CLIENT_SECRET
        refresh_token = self.user_refresh_token
        if not client_id or not client_secret:
            raise Exception("GITHUB_APP_CLIENT_ID / GITHUB_APP_CLIENT_SECRET not configured, cannot refresh user token")
        if not refresh_token:
            self._discard("no user refresh token stored")
            raise ReauthorizationRequired("No refresh token stored for this GitHub integration.")

        response = requests.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
            timeout=10,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        access_token = payload.get("access_token")
        if not access_token:
            error = payload.get("error")
            if error in _GITHUB_UNRECOVERABLE_REFRESH_ERRORS:
                self._discard(f"refresh rejected by GitHub: {error}")
                raise ReauthorizationRequired(f"GitHub refused the stored refresh token ({error}).")
            raise Exception(f"Unexpected refresh failure from GitHub: {error or response.status_code}")

        self._apply_user_token_payload(payload)

    def get_usable_user_access_token(self) -> str:
        """Return a non-expired user-to-server access token, refreshing on demand.

        Raises :class:`ReauthorizationRequired` if the row lacks tokens, the
        refresh token is expired, or GitHub rejects a refresh attempt.
        """
        if not self.user_access_token:
            self._discard("no user access token stored")
            raise ReauthorizationRequired("No user access token stored for this GitHub integration.")
        if self.user_refresh_token_expired():
            self._discard("user refresh token expired")
            raise ReauthorizationRequired("The stored GitHub user refresh token has expired.")
        if self.user_access_token_expired():
            self.refresh_user_access_token()
        token = self.user_access_token
        assert token is not None, "user_access_token cleared unexpectedly after refresh"
        return token

    def _apply_user_token_payload(self, payload: dict[str, Any]) -> None:
        """Write a fresh user token pair + expirations onto the integration row."""
        now = int(time.time())
        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token") or self.user_refresh_token
        access_expires_in = payload.get("expires_in")
        refresh_expires_in = payload.get("refresh_token_expires_in")

        self.integration.sensitive_config = {
            **(self.integration.sensitive_config or {}),
            "user_access_token": access_token,
            "user_refresh_token": refresh_token,
        }
        config = dict(self.integration.config or {})
        config["user_token_refreshed_at"] = now
        if access_expires_in is not None:
            config["user_access_token_expires_at"] = now + int(access_expires_in)
        if refresh_expires_in is not None:
            config["user_refresh_token_expires_at"] = now + int(refresh_expires_in)
        self.integration.config = config
        self.integration.save(update_fields=["sensitive_config", "config", "updated_at"])

    def _discard(self, reason: str) -> None:
        """Delete the integration when stored credentials are unusable.

        Deletion keeps the invariant that every integration row carries working tokens.
        The user falls back to the Connect flow.
        """
        logger.info("UserGitHubIntegration: discarding integration", user_id=self.integration.user_id, reason=reason)
        try:
            self.integration.delete()
        except Exception:
            logger.warning("UserGitHubIntegration: failed to delete unusable integration", exc_info=True)


def user_github_integration_from_installation(
    user: "User",
    *,
    installation_id: str,
    installation_info: dict[str, Any],
    installation_access_token: str,
    installation_token_expires_at: str,
    repository_selection: str,
    gh_id: int,
    gh_login: str,
    user_access_token: str,
    user_refresh_token: str | None,
    user_access_token_expires_in: int | None,
    user_refresh_token_expires_in: int | None,
) -> UserIntegration:
    """Create or update a UserIntegration from a GitHub App installation + user authorization.

    Called when a user installs the GitHub App and authorizes it in one flow.
    Writes both installation-level and user-level credentials atomically.
    """
    now = int(time.time())
    expires_in = datetime.fromisoformat(installation_token_expires_at).timestamp() - now

    config: dict[str, Any] = {
        "installation_id": installation_id,
        "expires_in": expires_in,
        "refreshed_at": now,
        "repository_selection": repository_selection,
        "account": {
            "type": (installation_info.get("account") or {}).get("type"),
            "name": (installation_info.get("account") or {}).get("login", installation_id),
        },
        "github_user": {"login": gh_login, "id": gh_id},
        "user_token_refreshed_at": now,
    }
    if user_access_token_expires_in is not None:
        config["user_access_token_expires_at"] = now + user_access_token_expires_in
    if user_refresh_token_expires_in is not None:
        config["user_refresh_token_expires_at"] = now + user_refresh_token_expires_in

    sensitive_config = {
        "access_token": installation_access_token,
        "user_access_token": user_access_token,
        "user_refresh_token": user_refresh_token,
    }

    integration, _created = UserIntegration.objects.update_or_create(
        user=user,
        kind="github",
        defaults={
            "integration_id": installation_id,
            "config": config,
            "sensitive_config": sensitive_config,
        },
    )
    return integration
