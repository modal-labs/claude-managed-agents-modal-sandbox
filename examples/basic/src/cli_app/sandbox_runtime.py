from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import modal
from modal.config import _lookup_workspace
from modal.config import config as modal_config

from config import MODAL_APP_NAME, MODAL_SESSION_VOLUME_PREFIX


SANDBOX_MONITOR_POLL_INTERVAL_SECONDS = 2.0
MODAL_DASHBOARD_BASE_URL = "https://modal.com"


@dataclass
class SandboxSnapshot:
    sandbox_id: str | None = None
    connection_url: str | None = None
    volume_path: str | None = None
    sandbox_url: str | None = None
    volume_url: str | None = None


class SandboxRuntime:
    def __init__(self) -> None:
        self._workspace_slug: str | None = None
        self._workspace_lookup_attempted = False

    def find_running_sandbox(self, session_id: str) -> modal.Sandbox | None:
        try:
            sb = modal.Sandbox.from_name(MODAL_APP_NAME, name=session_id)
        except modal.exception.NotFoundError:
            return None

        if sb.poll() is not None:
            return None

        return sb

    def connection_url(self, sb: modal.Sandbox, session_id: str) -> str:
        creds = sb.create_connect_token(user_metadata={"session_id": session_id})
        return f"{creds.url}/?_modal_connect_token={quote(creds.token, safe='')}"

    def dashboard_workspace_slug(self) -> str | None:
        override = os.environ.get("MODAL_WORKSPACE_SLUG")
        if override:
            return override

        if self._workspace_lookup_attempted:
            return self._workspace_slug

        self._workspace_lookup_attempted = True
        token_id = modal_config.get("token_id")
        token_secret = modal_config.get("token_secret")
        if not token_id or not token_secret:
            return None

        try:
            response = asyncio.run(
                _lookup_workspace(
                    modal_config.get("server_url"),
                    token_id,
                    token_secret,
                )
            )
        except Exception:
            return None

        self._workspace_slug = response.workspace_name or response.username or None
        return self._workspace_slug

    def sandbox_url(self, sandbox_id: str) -> str | None:
        workspace_slug = self.dashboard_workspace_slug()
        environment_name = modal_config.get("environment")
        if not workspace_slug or not environment_name:
            return None

        path = "/".join(
            (
                MODAL_DASHBOARD_BASE_URL,
                "apps",
                quote(workspace_slug, safe=""),
                quote(environment_name, safe=""),
                "deployed",
                quote(MODAL_APP_NAME, safe=""),
            )
        )
        query = urlencode({"activeTab": "sandboxes", "sandboxId": sandbox_id})
        return f"{path}?{query}"

    def volume_url(self, volume_name: str) -> str | None:
        workspace_slug = self.dashboard_workspace_slug()
        environment_name = modal_config.get("environment")
        if not workspace_slug or not environment_name:
            return None

        return "/".join(
            (
                MODAL_DASHBOARD_BASE_URL,
                "storage",
                quote(workspace_slug, safe=""),
                quote(environment_name, safe=""),
                "volumes",
                quote(volume_name, safe=""),
            )
        )

    def snapshot(
        self,
        session_id: str,
        *,
        create_connection_url: bool,
    ) -> SandboxSnapshot:
        sb = self.find_running_sandbox(session_id)
        if sb is None:
            return SandboxSnapshot()

        connection_url = None
        if create_connection_url:
            try:
                connection_url = self.connection_url(sb, session_id)
            except Exception:
                connection_url = None

        volume_name = f"{MODAL_SESSION_VOLUME_PREFIX}-{session_id}"
        return SandboxSnapshot(
            sandbox_id=sb.object_id,
            connection_url=connection_url,
            volume_path=f"{volume_name}/{session_id}",
            sandbox_url=self.sandbox_url(sb.object_id),
            volume_url=self.volume_url(volume_name),
        )


def wait_for_next_poll(stop_event) -> bool:
    return stop_event.wait(SANDBOX_MONITOR_POLL_INTERVAL_SECONDS)
