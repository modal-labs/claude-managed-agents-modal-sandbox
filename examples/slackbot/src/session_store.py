from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import modal

from config import SLACK_EVENTS_DICT_NAME, SLACK_SESSIONS_DICT_NAME


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slack_thread_key(
    *,
    enterprise_id: str | None,
    team_id: str,
    channel_id: str,
    thread_ts: str,
) -> str:
    ent = enterprise_id or "none"
    return f"slack:{ent}:{team_id}:{channel_id}:{thread_ts}"


def slack_thread_key_variants(
    *,
    enterprise_id: str | None,
    team_id: str,
    channel_id: str,
    thread_ts: str,
) -> list[str]:
    keys = [
        slack_thread_key(
            enterprise_id=enterprise_id,
            team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
    ]
    alias = slack_thread_key(
        enterprise_id=None,
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )
    if alias not in keys:
        keys.append(alias)
    return keys


def _sessions_dict() -> modal.Dict:
    return modal.Dict.from_name(SLACK_SESSIONS_DICT_NAME, create_if_missing=True)


def _events_dict() -> modal.Dict:
    return modal.Dict.from_name(SLACK_EVENTS_DICT_NAME, create_if_missing=True)


async def mark_event_seen(event_id: str, payload: dict[str, Any]) -> bool:
    event_type = (payload.get("event") or {}).get("type")
    value = {
        "event_id": event_id,
        "event_type": event_type,
        "seen_at": utc_now(),
        "event_time": payload.get("event_time"),
    }
    return await _events_dict().put.aio(event_id, value, skip_if_exists=True)


async def get_session(key: str) -> dict[str, Any] | None:
    return await _sessions_dict().get.aio(key, None)


async def find_session(keys: list[str]) -> tuple[str, dict[str, Any]] | None:
    for key in keys:
        record = await get_session(key)
        if record is not None:
            return key, record
    return None


async def put_session_if_absent(key: str, value: dict[str, Any]) -> bool:
    return await _sessions_dict().put.aio(key, value, skip_if_exists=True)


async def update_session(key: str, value: dict[str, Any]) -> None:
    await _sessions_dict().put.aio(key, value)


async def update_session_aliases(keys: list[str], value: dict[str, Any]) -> None:
    for key in keys:
        await update_session(key, value)
