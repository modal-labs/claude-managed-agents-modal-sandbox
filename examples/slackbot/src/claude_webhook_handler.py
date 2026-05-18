"""
Will create and run inside Modal fastapi_endpoint.
"""

import base64
import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path

import anthropic
import httpx
import modal
from anthropic.types.beta import UnwrapWebhookEvent
from fastapi import HTTPException, Request

from config import (
    APP_CONFIG_PATH,
    APP_LOG_LEVEL,
    APP_MODAL_APP_PATH,
    APP_PYPROJECT_TOML_PATH,
    APP_SANDBOX_IDLE_TIMEOUT_SECONDS,
    APP_SANDBOX_REPO_IMAGE_PATH,
    APP_SANDBOX_REPO_URL,
    APP_SANDBOX_REPO_WORKDIR_NAME,
    APP_SANDBOX_TIMEOUT_SECONDS,
    APP_SANDBOX_TOOL_RUNNER_PATH,
    APP_SANDBOX_WORKDIR,
    APP_UV_LOCK_PATH,
    MODAL_APP_NAME,
    MODAL_SESSION_VOLUME_PREFIX,
    anthropic_secret_env,
)
from modal_app import app


logging.Formatter.converter = time.gmtime
logging.basicConfig(
    format="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
for _name in ("webhook", "anthropic"):
    logging.getLogger(_name).setLevel(APP_LOG_LEVEL)
log = logging.getLogger("webhook")


async def _log_outgoing(request: httpx.Request) -> None:
    log.debug(f"{request.method} {request.url}")


secrets = modal.Secret.from_dict(anthropic_secret_env())

_config_src = Path(__file__).parent / "config.py"
_modal_app_src = Path(__file__).parent / "modal_app.py"
_sandbox_tool_runner_src = Path(__file__).parent / "sandbox_tool_runner.py"
_example_root = Path(__file__).parents[1]
_pyproject_toml_src = _example_root / "pyproject.toml"
_uv_lock_src = _example_root / "uv.lock"

webhook_image = (
    modal.Image.debian_slim(python_version="3.13")
    .uv_sync()
    # adding the config
    .add_local_file(_config_src, APP_CONFIG_PATH, copy=True)
    .add_local_file(_modal_app_src, APP_MODAL_APP_PATH, copy=True)
    # adding files that we need to build sandbox_image
    .add_local_file(
        _sandbox_tool_runner_src, APP_SANDBOX_TOOL_RUNNER_PATH, copy=True
    )
    .add_local_file(_pyproject_toml_src, APP_PYPROJECT_TOML_PATH, copy=True)
    .add_local_file(_uv_lock_src, APP_UV_LOCK_PATH, copy=True)
)

sandbox_image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("ca-certificates", "curl", "git")
    .run_commands(
        "mkdir -p -m 755 /etc/apt/keyrings",
        "curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg "
        "-o /etc/apt/keyrings/githubcli-archive-keyring.gpg",
        "chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg",
        'echo "deb [arch=$(dpkg --print-architecture) '
        "signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] "
        'https://cli.github.com/packages stable main" '
        "> /etc/apt/sources.list.d/github-cli.list",
        "apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*",
        f"git clone --depth 1 {APP_SANDBOX_REPO_URL} {APP_SANDBOX_REPO_IMAGE_PATH}",
        "git --version",
        "gh --version",
    )
    .uv_sync()
    .add_local_file(
        _sandbox_tool_runner_src, APP_SANDBOX_TOOL_RUNNER_PATH, copy=True
    )
)


def _signing_key() -> bytes:
    """Raw HMAC key bytes from a ``whsec_<base64>`` Standard Webhooks secret."""
    secret_str = os.environ["ANTHROPIC_WEBHOOK_SECRET"]
    if not secret_str.startswith("whsec_"):
        raise ValueError("ANTHROPIC_WEBHOOK_SECRET missing whsec_ prefix")
    raw = secret_str.removeprefix("whsec_").replace("+", "-").replace("/", "_")
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))


def _verify_webhook(raw: bytes, headers: "Mapping[str, str]") -> UnwrapWebhookEvent:
    """Standard Webhooks verification via the SDK."""
    try:
        return anthropic.Anthropic().beta.webhooks.unwrap(
            raw.decode(), headers=headers, key=_signing_key()
        )
    except Exception as e:
        # standardwebhooks raises WebhookVerificationError; ValueError can come
        # from _signing_key. Neither should expose request payload contents.
        log.warning(f"signature reject: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=401, detail="signature verification failed"
        ) from None


async def _find_live_sandbox(key: str) -> modal.Sandbox | None:
    try:
        sb = await modal.Sandbox.from_name.aio(MODAL_APP_NAME, name=key)
    except modal.exception.NotFoundError:
        return None
    return sb if await sb.poll.aio() is None else None


async def _create_sandbox(
    session_id: str,
    *,
    environment_id: str,
    work_id: str,
    environment_key: str,
    sandbox_timeout: int,
) -> modal.Sandbox:
    sb_app = await modal.App.lookup.aio(MODAL_APP_NAME, create_if_missing=True)
    session_vol = modal.Volume.from_name(
        f"{MODAL_SESSION_VOLUME_PREFIX}-{session_id}", create_if_missing=True
    )
    sb = await modal.Sandbox.create.aio(
        "python",
        APP_SANDBOX_TOOL_RUNNER_PATH,
        app=sb_app,
        name=session_id,
        image=sandbox_image,
        timeout=sandbox_timeout,
        volumes={APP_SANDBOX_WORKDIR: session_vol},
        env={
            "ANTHROPIC_SESSION_ID": session_id,
            "ANTHROPIC_ENVIRONMENT_ID": environment_id,
            "ANTHROPIC_WORK_ID": work_id,
            "ANTHROPIC_ENVIRONMENT_KEY": environment_key,
            "APP_LOG_LEVEL": APP_LOG_LEVEL,
            "APP_SANDBOX_REPO_IMAGE_PATH": APP_SANDBOX_REPO_IMAGE_PATH,
            "APP_SANDBOX_REPO_WORKDIR_NAME": APP_SANDBOX_REPO_WORKDIR_NAME,
            "APP_SANDBOX_IDLE_TIMEOUT_SECONDS": str(
                APP_SANDBOX_IDLE_TIMEOUT_SECONDS
            ),
            "APP_SANDBOX_WORKDIR": APP_SANDBOX_WORKDIR,
        },
    )
    await sb.set_tags.aio({"session_id": session_id})
    return sb


async def _process_work_item(
    *,
    session_id: str,
    work_id: str,
    environment_id: str,
    environment_key: str,
) -> dict:
    """Get-or-create a Modal Sandbox for one already-ack'd work item."""
    existing = await _find_live_sandbox(session_id)
    if existing is not None:
        log.info(
            f"work={work_id} session={session_id} "
            f"sandbox={existing.object_id} (live)"
        )
        return {
            "session_id": session_id,
            "work_id": work_id,
            "sandbox_id": existing.object_id,
            "created": False,
        }

    sb = await _create_sandbox(
        session_id,
        environment_id=environment_id,
        work_id=work_id,
        environment_key=environment_key,
        sandbox_timeout=APP_SANDBOX_TIMEOUT_SECONDS,
    )
    log.info(
        f"work={work_id} session={session_id} "
        f"sandbox={sb.object_id} (created)"
    )
    return {
        "session_id": session_id,
        "work_id": work_id,
        "sandbox_id": sb.object_id,
        "created": True,
    }


async def _drain_work(environment_id: str) -> list[dict]:
    """Poll until the queue is empty, spawning a sandbox per work item."""
    environment_key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
    spawned: list[dict] = []
    failed: list[dict] = []
    async with httpx.AsyncClient(event_hooks={"request": [_log_outgoing]}) as http_client:
        client = anthropic.AsyncAnthropic(
            auth_token=environment_key,
            http_client=http_client,
        )
        async for work in client.beta.environments.work.poller(
            environment_id=environment_id,
            environment_key=environment_key,
            # None -> omit -> non-blocking. The API rejects block_ms=0.
            block_ms=None,
            reclaim_older_than_ms=2000,
            drain=True,
            auto_stop=False,
        ):
            if work.data.type != "session":
                log.info(f"skipping work={work.id} type={work.data.type}")
                continue
            session_id = work.data.id
            try:
                spawned.append(
                    await _process_work_item(
                        session_id=session_id,
                        work_id=work.id,
                        environment_id=work.environment_id,
                        environment_key=environment_key,
                    )
                )
            except Exception as e:
                detail = type(e).__name__
                log.exception(
                    "FAILED work=%s session=%s: %s: %s",
                    work.id,
                    session_id,
                    detail,
                    e,
                )
                failed.append(
                    {"work_id": work.id, "session_id": session_id, "error": detail}
                )
    if failed:
        log.warning(f"drain finished: spawned={len(spawned)} failed={len(failed)}")
    return spawned + failed


@app.function(image=webhook_image, secrets=[secrets])
@modal.fastapi_endpoint(method="POST")
async def webhook(request: Request) -> dict:
    raw = await request.body()
    event = _verify_webhook(raw, request.headers)
    ev_type = event.data.type
    log.info(f"event={ev_type} session_id={event.data.id}")

    if ev_type != "session.status_run_started":
        log.info(f"ignored event={ev_type} session_id={event.data.id}")
        return {"status": "ignored", "event_type": ev_type}

    spawned = await _drain_work(os.environ["ANTHROPIC_ENVIRONMENT_ID"])
    if not spawned:
        log.info(f"event={ev_type} session_id={event.data.id} but queue empty")
    return {"status": "ok", "event_type": ev_type, "spawned": spawned}
