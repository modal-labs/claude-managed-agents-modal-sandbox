"""
Slack Events API webhook for mapping Slack assistant threads to Anthropic sessions.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import modal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agent_bridge import (
    create_session,
    post_slack_message,
    send_user_message,
    session_ack_text,
    stream_session_events_to_slack,
)
from config import (
    APP_AGENT_BRIDGE_PATH,
    APP_CONFIG_PATH,
    APP_MODAL_APP_PATH,
    APP_PYPROJECT_TOML_PATH,
    APP_SESSION_STORE_PATH,
    APP_UV_LOCK_PATH,
    slack_secret_env,
)
from modal_app import app
from session_store import (
    find_session,
    mark_event_seen,
    put_session_if_absent,
    slack_thread_key_variants,
    update_session_aliases,
    utc_now,
)


secrets = modal.Secret.from_dict(slack_secret_env())
web_app = FastAPI()

_example_root = Path(__file__).parents[1]
_config_src = Path(__file__).parent / "config.py"
_modal_app_src = Path(__file__).parent / "modal_app.py"
_agent_bridge_src = Path(__file__).parent / "agent_bridge.py"
_session_store_src = Path(__file__).parent / "session_store.py"
_pyproject_toml_src = _example_root / "pyproject.toml"
_uv_lock_src = _example_root / "uv.lock"

webhook_image = (
    modal.Image.debian_slim(python_version="3.13")
    .uv_sync()
    .add_local_file(_config_src, APP_CONFIG_PATH, copy=True)
    .add_local_file(_modal_app_src, APP_MODAL_APP_PATH, copy=True)
    .add_local_file(_agent_bridge_src, APP_AGENT_BRIDGE_PATH, copy=True)
    .add_local_file(_session_store_src, APP_SESSION_STORE_PATH, copy=True)
    .add_local_file(_pyproject_toml_src, APP_PYPROJECT_TOML_PATH, copy=True)
    .add_local_file(_uv_lock_src, APP_UV_LOCK_PATH, copy=True)
)


def _verify_slack_signature(raw_body: bytes, request: Request) -> None:
    secret = os.environ["SLACK_SIGNING_SECRET"]
    timestamp = request.headers.get("x-slack-request-timestamp")
    signature = request.headers.get("x-slack-signature")
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="missing slack signature headers")
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="malformed slack timestamp") from None
    if abs(time.time() - ts) > 300:
        raise HTTPException(status_code=401, detail="stale slack timestamp")

    base = b"v0:" + timestamp.encode() + b":" + raw_body
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="bad slack signature")


def _first_authorization(payload: dict[str, Any]) -> dict[str, Any]:
    authorizations = payload.get("authorizations") or []
    return authorizations[0] if authorizations else {}


def _thread_info_from_assistant_event(
    payload: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any]:
    assistant_thread = event.get("assistant_thread") or {}
    context = assistant_thread.get("context") or {}
    auth = _first_authorization(payload)
    return {
        "enterprise_id": context.get("enterprise_id")
        or payload.get("enterprise_id")
        or auth.get("enterprise_id"),
        "team_id": context.get("team_id")
        or payload.get("team_id")
        or auth.get("team_id")
        or event.get("team"),
        "channel_id": assistant_thread.get("channel_id"),
        "thread_ts": assistant_thread.get("thread_ts"),
        "user_id": assistant_thread.get("user_id"),
        "context": context,
    }


def _thread_info_from_message(
    payload: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any]:
    auth = _first_authorization(payload)
    return {
        "enterprise_id": payload.get("enterprise_id") or auth.get("enterprise_id"),
        "team_id": payload.get("team_id") or auth.get("team_id") or event.get("team"),
        "channel_id": event.get("channel"),
        "thread_ts": event.get("thread_ts") or event.get("ts"),
        "user_id": event.get("user"),
        "context": {},
    }


def _clean_message_text(text: str) -> str:
    return re.sub(r"<@[A-Z0-9]+>", "", text).strip()


def _log_step(step: str, **fields: Any) -> None:
    details = " ".join(
        f"{key}={value}"
        for key, value in fields.items()
        if value is not None
    )
    suffix = f" {details}" if details else ""
    print(f"[slack] {step}{suffix}", flush=True)


def _validate_thread_info(info: dict[str, Any]) -> None:
    missing = [
        name
        for name in ("team_id", "channel_id", "thread_ts")
        if not info.get(name)
    ]
    if missing:
        raise ValueError(f"missing Slack thread fields: {', '.join(missing)}")


def _base_session_record(info: dict[str, Any], *, status: str) -> dict[str, Any]:
    now = utc_now()
    return {
        "anthropic_session_id": None,
        "slack": {
            "enterprise_id": info.get("enterprise_id"),
            "team_id": info["team_id"],
            "channel_id": info["channel_id"],
            "thread_ts": info["thread_ts"],
            "user_id": info.get("user_id"),
        },
        "context": info.get("context") or {},
        "created_at": now,
        "updated_at": now,
        "status": status,
    }


async def _wait_for_active_session(keys: list[str]) -> dict[str, Any] | None:
    for _ in range(10):
        found = await find_session(keys)
        if found is not None:
            _, record = found
            if record.get("anthropic_session_id"):
                return record
        await asyncio.sleep(1)
    return None


async def _ensure_session(info: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    _validate_thread_info(info)
    keys = slack_thread_key_variants(
        enterprise_id=info.get("enterprise_id"),
        team_id=info["team_id"],
        channel_id=info["channel_id"],
        thread_ts=info["thread_ts"],
    )
    creating = _base_session_record(info, status="creating")
    is_new_mapping = False

    found = await find_session(keys)
    if found is not None:
        _, record = found
        if record.get("anthropic_session_id"):
            _log_step(
                "claude.session.reuse",
                session_id=record.get("anthropic_session_id"),
                channel_id=info["channel_id"],
                thread_ts=info["thread_ts"],
            )
            return record, False
        active = await _wait_for_active_session(keys)
        if active is not None:
            _log_step(
                "claude.session.reuse_after_wait",
                session_id=active.get("anthropic_session_id"),
                channel_id=info["channel_id"],
                thread_ts=info["thread_ts"],
            )
            return active, False
        creating = {
            **record,
            "status": "creating",
            "updated_at": utc_now(),
            "last_error": None,
        }
        await update_session_aliases(keys, creating)
    else:
        created = await put_session_if_absent(keys[0], creating)
        if not created:
            active = await _wait_for_active_session(keys)
            if active is not None:
                return active, False
            found = await find_session(keys)
            creating = {
                **(found[1] if found is not None else creating),
                "status": "creating",
                "updated_at": utc_now(),
                "last_error": None,
            }
        else:
            is_new_mapping = True

        for alias in keys[1:]:
            await put_session_if_absent(alias, creating)

    try:
        _log_step(
            "claude.session.create.start",
            channel_id=info["channel_id"],
            thread_ts=info["thread_ts"],
            user_id=info.get("user_id"),
        )
        session_id = create_session(slack_record=creating)
    except Exception as exc:
        _log_step(
            "claude.session.create.error",
            channel_id=info["channel_id"],
            thread_ts=info["thread_ts"],
            error=f"{type(exc).__name__}: {exc}",
        )
        failed = {
            **creating,
            "updated_at": utc_now(),
            "status": "error",
            "last_error": f"{type(exc).__name__}: {exc}",
        }
        await update_session_aliases(keys, failed)
        raise

    _log_step(
        "claude.session.create.done",
        session_id=session_id,
        channel_id=info["channel_id"],
        thread_ts=info["thread_ts"],
    )
    active = {
        **creating,
        "anthropic_session_id": session_id,
        "updated_at": utc_now(),
        "status": "active",
        "last_error": None,
    }
    await update_session_aliases(keys, active)
    return active, is_new_mapping


def _post_ack_link(*, bot_token: str, record: dict[str, Any]) -> None:
    """Post the ack-as-session-link on first contact with a new session."""
    post_slack_message(
        bot_token=bot_token,
        channel_id=record["slack"]["channel_id"],
        thread_ts=record["slack"]["thread_ts"],
        text=session_ack_text(record["anthropic_session_id"]),
    )


async def _handle_thread_started(payload: dict[str, Any], event: dict[str, Any]) -> None:
    bot_token = os.environ["SLACK_BOT_TOKEN"]
    info = _thread_info_from_assistant_event(payload, event)
    _log_step(
        "assistant_thread_started.ensure_session",
        channel_id=info.get("channel_id"),
        thread_ts=info.get("thread_ts"),
        user_id=info.get("user_id"),
    )
    record, created = await _ensure_session(info)
    if created:
        _post_ack_link(bot_token=bot_token, record=record)


async def _handle_context_changed(payload: dict[str, Any], event: dict[str, Any]) -> None:
    info = _thread_info_from_assistant_event(payload, event)
    _validate_thread_info(info)
    _log_step(
        "assistant_thread_context_changed",
        channel_id=info["channel_id"],
        thread_ts=info["thread_ts"],
    )
    keys = slack_thread_key_variants(
        enterprise_id=info.get("enterprise_id"),
        team_id=info["team_id"],
        channel_id=info["channel_id"],
        thread_ts=info["thread_ts"],
    )
    found = await find_session(keys)
    if found is None:
        return
    _, record = found
    updated = {**record, "context": info.get("context") or {}, "updated_at": utc_now()}
    await update_session_aliases(keys, updated)


async def _handle_user_message(payload: dict[str, Any], event: dict[str, Any]) -> None:
    if event.get("bot_id") or event.get("subtype"):
        _log_step(
            "message.ignored",
            reason="bot_or_subtype",
            subtype=event.get("subtype"),
            bot_id=event.get("bot_id"),
        )
        return

    raw_text = event.get("text") or ""
    text = _clean_message_text(raw_text)
    if not text:
        _log_step("message.ignored", reason="empty_text")
        return

    bot_token = os.environ["SLACK_BOT_TOKEN"]
    info = _thread_info_from_message(payload, event)
    _log_step(
        "message.ensure_session",
        channel_id=info.get("channel_id"),
        thread_ts=info.get("thread_ts"),
        user_id=info.get("user_id"),
        text_len=len(text),
    )
    record, created = await _ensure_session(info)

    if created:
        _post_ack_link(bot_token=bot_token, record=record)

    session_id = record["anthropic_session_id"]
    _log_step("claude.user_message.send.start", session_id=session_id, text_len=len(text))
    send_user_message(session_id=session_id, text=text)
    _log_step("claude.user_message.send.done", session_id=session_id)
    _log_step("claude.events.stream.start", session_id=session_id)
    stream_session_events_to_slack(
        session_id=session_id,
        bot_token=bot_token,
        channel_id=record["slack"]["channel_id"],
        thread_ts=record["slack"]["thread_ts"],
    )
    _log_step("claude.events.stream.done", session_id=session_id)


@app.function(image=webhook_image, secrets=[secrets], timeout=900)
async def handle_slack_event(payload: dict[str, Any]) -> None:
    event = payload.get("event") or {}
    event_type = event.get("type")
    _log_step(
        "event.process.start",
        event_id=payload.get("event_id"),
        event_type=event_type,
        team_id=payload.get("team_id"),
        retry_num=payload.get("retry_num"),
    )
    if event_type == "assistant_thread_started":
        await _handle_thread_started(payload, event)
    elif event_type == "assistant_thread_context_changed":
        await _handle_context_changed(payload, event)
    elif event_type in ("message", "app_mention"):
        await _handle_user_message(payload, event)
    else:
        _log_step("event.ignored", event_type=event_type)
    _log_step(
        "event.process.done",
        event_id=payload.get("event_id"),
        event_type=event_type,
    )


async def _handle_slack_request(request: Request) -> JSONResponse | PlainTextResponse:
    raw = await request.body()
    _log_step(
        "slack_events.request.received",
        method=request.method,
        path=request.url.path,
        body_len=len(raw),
        retry_num=request.headers.get("x-slack-retry-num"),
        retry_reason=request.headers.get("x-slack-retry-reason"),
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        _log_step("slack_events.request.invalid_json", body_len=len(raw))
        raise HTTPException(status_code=400, detail="invalid json") from None

    if payload.get("type") == "url_verification":
        _log_step(
            "slack_events.url_verification",
            challenge_len=len(payload.get("challenge") or ""),
        )
        return PlainTextResponse(payload.get("challenge") or "")

    _verify_slack_signature(raw, request)
    event = payload.get("event") or {}
    event_id = payload.get("event_id")
    event_type = event.get("type")
    _log_step(
        "slack_events.signature.verified",
        event_id=event_id,
        event_type=event_type,
        team_id=payload.get("team_id"),
    )

    if event_id:
        is_new = await mark_event_seen(event_id, payload)
        _log_step(
            "slack_events.dedupe.checked",
            event_id=event_id,
            event_type=event_type,
            is_new=is_new,
        )
        if not is_new:
            _log_step(
                "slack_events.duplicate.ack",
                event_id=event_id,
                event_type=event_type,
            )
            return JSONResponse({"ok": True, "duplicate": True})
    else:
        _log_step("slack_events.dedupe.skipped", reason="missing_event_id")

    _log_step(
        "slack_events.spawn.start",
        event_id=event_id,
        event_type=event_type,
    )
    call = await handle_slack_event.spawn.aio(payload)
    _log_step(
        "slack_events.spawn.done",
        event_id=event_id,
        event_type=event_type,
        call_id=getattr(call, "object_id", None),
    )
    return JSONResponse({"ok": True})


@web_app.post("/", response_model=None)
async def slack_events_root(request: Request) -> JSONResponse | PlainTextResponse:
    return await _handle_slack_request(request)


@web_app.post("/slack/events", response_model=None)
async def slack_events_path(request: Request) -> JSONResponse | PlainTextResponse:
    return await _handle_slack_request(request)


@app.function(image=webhook_image, secrets=[secrets], timeout=30)
@modal.asgi_app()
def slack_events() -> FastAPI:
    return web_app
