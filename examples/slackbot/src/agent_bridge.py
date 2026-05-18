from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from typing import Any

import anthropic

SLACK_EVENT_CHUNK_CHARS = 3500

# Rotated at random for the session.status_running ack, just for fun.
_ACK_VERBS = (
    "manifesting",
    "marinating",
    "meandering",
    "metamorphosing",
    "misting",
    "moonwalking",
    "moseying",
    "mulling",
    "mustering",
    "musing",
)


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required secret key: {name}")
    return value


def create_anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=_required_env("ANTHROPIC_API_KEY"))


def session_url(session_id: str) -> str | None:
    """Claude Platform URL for a session, or None when the workspace ID isn't set."""
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if not workspace_id or workspace_id == "wrkspc_xxx":
        return None
    return f"https://platform.claude.com/workspaces/{workspace_id}/sessions/{session_id}"


def session_ack_text(session_id: str) -> str:
    """Ack message for a freshly created session, with an embedded session
    link when the workspace ID is configured."""
    verb = random.choice(_ACK_VERBS)
    url = session_url(session_id)
    if url is None:
        return f"Currently {verb}…"
    return f"Created <{url}|session>. Currently {verb}…"


def create_session(*, slack_record: dict[str, Any]) -> str:
    client = create_anthropic_client()
    slack = slack_record["slack"]
    metadata = {
        "slack_team_id": slack["team_id"],
        "slack_channel_id": slack["channel_id"],
        "slack_thread_ts": slack["thread_ts"],
        "slack_user_id": slack.get("user_id") or "",
    }
    if slack.get("enterprise_id"):
        metadata["slack_enterprise_id"] = slack["enterprise_id"]

    session = client.beta.sessions.create(
        agent=_required_env("ANTHROPIC_AGENT_ID"),
        environment_id=_required_env("ANTHROPIC_ENVIRONMENT_ID"),
        metadata=metadata,
        title=f"Slack {slack['channel_id']} {slack['thread_ts']}",
    )
    return session.id


def send_user_message(*, session_id: str, text: str) -> None:
    client = create_anthropic_client()
    client.beta.sessions.events.send(
        session_id,
        events=[{"type": "user.message", "content": [{"type": "text", "text": text}]}],
    )


def slack_api_post(
    *,
    bot_token: str,
    method: str,
    payload: dict[str, Any],
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=body,
        headers={
            "authorization": f"Bearer {bot_token}",
            "content-type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            response_body = resp.read()
    except urllib.error.HTTPError as exc:
        response_body = exc.read()
        raise RuntimeError(
            f"Slack API {method} HTTP {exc.code}: "
            f"{response_body.decode(errors='replace')}"
        ) from exc

    data = json.loads(response_body)
    if not data.get("ok"):
        raise RuntimeError(f"Slack API {method} failed: {data}")
    return data


def post_slack_message(
    *,
    bot_token: str,
    channel_id: str,
    thread_ts: str,
    text: str,
) -> dict[str, Any]:
    return slack_api_post(
        bot_token=bot_token,
        method="chat.postMessage",
        payload={"channel": channel_id, "thread_ts": thread_ts, "text": text},
    )


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _block_text(block: Any) -> str | None:
    """Pull a string out of one CMA content block, regardless of shape."""
    if hasattr(block, "model_dump"):
        block = block.model_dump(mode="json")
    if not isinstance(block, dict):
        return None
    return block.get("text") or block.get("thinking") or None


def _extract_text(content: Any) -> str:
    if not content:
        return ""
    parts = [t for t in (_block_text(b) for b in content) if t]
    return "\n".join(parts)


def format_event_messages(event: Any) -> list[str]:
    """Slack messages for the final agent reply only; everything else is dropped."""
    if getattr(event, "type", "") != "agent.message":
        return []
    text = _extract_text(getattr(event, "content", None))
    return _chunks(text, SLACK_EVENT_CHUNK_CHARS) if text else []


def _stop_reason_type(event: Any) -> str | None:
    reason = getattr(event, "stop_reason", None)
    if reason is None:
        return None
    if isinstance(reason, dict):
        return reason.get("type")
    return getattr(reason, "type", None)


def stream_session_events_to_slack(
    *,
    session_id: str,
    bot_token: str,
    channel_id: str,
    thread_ts: str,
) -> None:
    client = create_anthropic_client()
    try:
        with client.beta.sessions.events.stream(session_id, timeout=300) as stream:
            for event in stream:
                for message in format_event_messages(event):
                    post_slack_message(
                        bot_token=bot_token,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        text=message,
                    )
                if (
                    event.type == "session.status_idle"
                    and _stop_reason_type(event) != "requires_action"
                ):
                    return
    except Exception as exc:
        post_slack_message(
            bot_token=bot_token,
            channel_id=channel_id,
            thread_ts=thread_ts,
            text=(
                "*slackbot.stream_error*\n"
                f"```text\n{type(exc).__name__}: {exc}\n```"
            ),
        )
