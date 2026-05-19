from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import anthropic

from app.state import EventBlock


TOOL_EVENT_TYPES = {
    "agent.tool_use",
    "agent.tool_result",
    "agent.mcp_tool_use",
    "agent.mcp_tool_result",
    "agent.custom_tool_use",
    "user.tool_result",
}
USER_EVENT_TYPES = {"user.message"}
SESSION_READY_EVENT_TYPES = {"session.status_idle"}
SESSION_RUNNING_EVENT_TYPES = {"session.status_running"}


@dataclass
class SessionReplay:
    agent_id: str
    agent_url: str | None
    environment_id: str
    environment_url: str | None
    session_id: str
    session_url: str | None
    blocks: list[EventBlock]
    seen_event_ids: set[str]
    input_ready: bool


@dataclass
class SessionEventUpdate:
    event_id: str | None
    blocks: list[EventBlock]
    user_text: str | None
    input_ready: bool | None


@dataclass
class InputStateTracker:
    input_ready: bool = False
    waiting_for_agent_message: bool = False
    agent_message_seen: bool = False

    def apply(self, event: object) -> bool | None:
        event_type = getattr(event, "type", "")
        if event_type in SESSION_RUNNING_EVENT_TYPES:
            self.input_ready = False
            self.waiting_for_agent_message = False
            self.agent_message_seen = False
            return False

        if event_type == "agent.message":
            self.agent_message_seen = True
            if self.waiting_for_agent_message:
                self.input_ready = True
                self.waiting_for_agent_message = False
                return True
            return None

        if event_type in SESSION_READY_EVENT_TYPES:
            if _stop_reason_type(event) == "requires_action":
                self.input_ready = False
                self.waiting_for_agent_message = False
                return False
            if self.agent_message_seen:
                self.input_ready = True
                return True
            self.waiting_for_agent_message = True
            return None

        return None


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def _text_content(blocks: list[object] | None) -> str:
    if not blocks:
        return ""
    return "\n\n".join(
        block.text for block in blocks if getattr(block, "type", None) == "text"
    )


def _block_text(block: Any) -> str | None:
    if hasattr(block, "model_dump"):
        block = block.model_dump(mode="json")
    if not isinstance(block, dict):
        return None
    return block.get("text") or block.get("thinking") or None


def _extract_text(content: Any) -> str:
    if not content:
        return ""
    parts = [text for text in (_block_text(block) for block in content) if text]
    return "\n".join(parts)


def _event_id(event: object) -> str | None:
    value = getattr(event, "id", None)
    if isinstance(value, str):
        return value
    if hasattr(event, "to_dict"):
        event_data = event.to_dict(mode="json")
        value = event_data.get("id")
        return value if isinstance(value, str) else None
    return None


def _event_context(event_data: dict[str, object]) -> str:
    keys = ("tool_use_id", "mcp_tool_use_id", "id", "session_thread_id")
    if any(key in event_data for key in ("tool_use_id", "mcp_tool_use_id")):
        keys = ("tool_use_id", "mcp_tool_use_id")
    parts = [f"{key}={value}" for key in keys if (value := event_data.get(key))]
    return f" {' '.join(parts)}" if parts else ""


def _stop_reason_type(event: object) -> str | None:
    reason = getattr(event, "stop_reason", None)
    if reason is None:
        return None
    if isinstance(reason, dict):
        return reason.get("type")
    return getattr(reason, "type", None)


def _user_event_text(event: object) -> str | None:
    if getattr(event, "type", "") not in USER_EVENT_TYPES:
        return None
    text = _text_content(getattr(event, "content", None))
    return text.strip() or None


def _event_blocks(event: object) -> list[EventBlock]:
    event_type = event.type
    if event_type in USER_EVENT_TYPES:
        event_data = event.to_dict(mode="json")
        body = _text_content(getattr(event, "content", None)) or event_data
        return [EventBlock("user.message", body, "bright_blue")]

    if event_type == "agent.message":
        text = _extract_text(getattr(event, "content", None))
        return [EventBlock("agent.message", text, "orange1")] if text else []

    if event_type in TOOL_EVENT_TYPES:
        event_data = event.to_dict(mode="json")
        tool_name = event_data.get("name", "tool")
        if "mcp_server_name" in event_data:
            tool_name = f"{event_data['mcp_server_name']}.{tool_name}"
        event_context = _event_context(event_data)
        if event_type.endswith("_use"):
            body = event_data.get("input", {})
            title = f"{event_type}: {tool_name}{event_context}"
        else:
            body = _text_content(event.content) or event_data
            title = f"{event_type}: error={event_data.get('is_error')}{event_context}"
        return [EventBlock(title, body, "dim")]

    return []


@dataclass
class AgentRuntime:
    client: anthropic.Anthropic = field(default_factory=anthropic.Anthropic)

    @classmethod
    def from_env(cls) -> "AgentRuntime":
        return cls(
            client=anthropic.Anthropic(api_key=_required_env("ANTHROPIC_API_KEY"))
        )

    def platform_url(self, resource: str, resource_id: str) -> str | None:
        workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        if not workspace_id or workspace_id == "wrkspc_xxx":
            return None
        if resource_id.endswith("_xxx"):
            return None
        return (
            f"https://platform.claude.com/workspaces/{workspace_id}"
            f"/{resource}/{resource_id}"
        )

    def agent_id(self) -> str:
        return _required_env("ANTHROPIC_AGENT_ID")

    def agent_url(self, agent_id: str) -> str | None:
        return self.platform_url("agents", agent_id)

    def environment_id(self) -> str:
        return _required_env("ANTHROPIC_ENVIRONMENT_ID")

    def environment_url(self, environment_id: str) -> str | None:
        return self.platform_url("environments", environment_id)

    def session_url(self, session_id: str) -> str | None:
        return self.platform_url("sessions", session_id)

    def create_session(self) -> str:
        session = self.client.beta.sessions.create(
            agent=self.agent_id(),
            environment_id=self.environment_id(),
        )
        return session.id

    def send_user_message(self, *, session_id: str, text: str) -> None:
        self.client.beta.sessions.events.send(
            session_id,
            events=[
                {"type": "user.message", "content": [{"type": "text", "text": text}]}
            ],
        )

    def replay_session(self, session_id: str) -> SessionReplay:
        agent_id = self.agent_id()
        environment_id = self.environment_id()
        tracker = InputStateTracker()
        blocks: list[EventBlock] = []
        seen_event_ids: set[str] = set()
        for event in self.client.beta.sessions.events.list(session_id, order="asc"):
            if event_id := _event_id(event):
                seen_event_ids.add(event_id)
            blocks.extend(_event_blocks(event))
            tracker.apply(event)

        return SessionReplay(
            agent_id=agent_id,
            agent_url=self.agent_url(agent_id),
            environment_id=environment_id,
            environment_url=self.environment_url(environment_id),
            session_id=session_id,
            session_url=self.session_url(session_id),
            blocks=blocks,
            seen_event_ids=seen_event_ids,
            input_ready=tracker.input_ready,
        )

    def start_session(self, *, resume_session_id: str | None) -> SessionReplay:
        if resume_session_id:
            return self.replay_session(resume_session_id)

        session_id = self.create_session()
        replay = self.replay_session(session_id)
        if not replay.seen_event_ids:
            replay.input_ready = True
        return replay

    def stream_events(
        self,
        *,
        session_id: str,
        seen_event_ids: set[str],
    ):
        tracker = InputStateTracker()
        with self.client.beta.sessions.events.stream(session_id) as stream:
            for event in stream:
                event_id = _event_id(event)
                if event_id in seen_event_ids:
                    continue
                if event_id:
                    seen_event_ids.add(event_id)
                yield SessionEventUpdate(
                    event_id=event_id,
                    blocks=_event_blocks(event),
                    user_text=_user_event_text(event),
                    input_ready=tracker.apply(event),
                )
