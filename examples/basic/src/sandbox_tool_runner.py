"""
Will run inside the Modal Sandbox
"""

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

import httpx
from anthropic import AsyncAnthropic


APP_SANDBOX_IDLE_TIMEOUT_SECONDS = float(os.environ["APP_SANDBOX_IDLE_TIMEOUT_SECONDS"])
APP_SANDBOX_WORKDIR = os.environ["APP_SANDBOX_WORKDIR"]
APP_SANDBOX_REPO_IMAGE_PATH = os.environ["APP_SANDBOX_REPO_IMAGE_PATH"]
APP_SANDBOX_REPO_WORKDIR_NAME = os.environ["APP_SANDBOX_REPO_WORKDIR_NAME"]
APP_LOG_LEVEL = os.environ["APP_LOG_LEVEL"].upper()


logging.Formatter.converter = time.gmtime
logging.basicConfig(
    format="%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)
for _name in ("runner", "anthropic"):
    logging.getLogger(_name).setLevel(APP_LOG_LEVEL)
log = logging.getLogger("runner")


async def _log_outgoing(request: httpx.Request) -> None:
    log.debug(f"{request.method} {request.url}")


def _seed_repository() -> None:
    src = Path(APP_SANDBOX_REPO_IMAGE_PATH)
    dest = Path(APP_SANDBOX_WORKDIR) / APP_SANDBOX_REPO_WORKDIR_NAME
    if dest.exists():
        log.info(f"repo already present path={dest}")
        return
    shutil.copytree(src, dest, symlinks=True)
    log.info(f"seeded repo src={src} dest={dest}")


async def main() -> None:
    environment_key = os.environ["ANTHROPIC_ENVIRONMENT_KEY"]
    work_id = os.environ["ANTHROPIC_WORK_ID"]
    session_id = os.environ["ANTHROPIC_SESSION_ID"]
    log.info(f"attaching session={session_id} work={work_id}")
    _seed_repository()

    async with httpx.AsyncClient(event_hooks={"request": [_log_outgoing]}) as http_client:
        client = AsyncAnthropic(auth_token=environment_key, http_client=http_client)
        await client.beta.environments.work.worker(
            environment_key=environment_key,
            workdir=APP_SANDBOX_WORKDIR,
            unrestricted_paths=True,
            max_idle=APP_SANDBOX_IDLE_TIMEOUT_SECONDS,
        ).handle_item()


if __name__ == "__main__":
    asyncio.run(main())
