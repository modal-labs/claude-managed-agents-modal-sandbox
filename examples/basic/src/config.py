import os
from pathlib import Path

import dotenv


EXAMPLE_ROOT = Path(__file__).parents[1]


def load_env() -> None:
    dotenv.load_dotenv(EXAMPLE_ROOT / ".env")
    dotenv.load_dotenv(EXAMPLE_ROOT / ".env.local", override=True)


load_env()


ANTHROPIC_SECRET_ENV_KEYS = (
    "ANTHROPIC_AGENT_ID",
    "ANTHROPIC_ENVIRONMENT_ID",
    "ANTHROPIC_ENVIRONMENT_KEY",
    "ANTHROPIC_WEBHOOK_SECRET",
)

MODAL_APP_NAME = "claude-managed-agents-basic"
MODAL_SESSION_VOLUME_PREFIX = "cma-basic-session"  # short to avoid the 64 characters limit

APP_LOG_LEVEL = "INFO"
APP_SANDBOX_WORKDIR = "/workspace"
APP_SANDBOX_IDLE_TIMEOUT_SECONDS = 60.0
APP_SANDBOX_TIMEOUT_SECONDS = 600
APP_SANDBOX_REPO_URL = "https://github.com/modal-labs/modal-examples.git"
APP_SANDBOX_REPO_IMAGE_PATH = "/opt/modal-examples"
APP_SANDBOX_REPO_WORKDIR_NAME = "modal-examples"

APP_CONFIG_PATH = "/root/config.py"
APP_SANDBOX_TOOL_RUNNER_PATH = "/root/sandbox_tool_runner.py"
APP_PYPROJECT_TOML_PATH = "/root/pyproject.toml"
APP_UV_LOCK_PATH = "/root/uv.lock"


def anthropic_secret_env() -> dict[str, str]:
    return {key: os.environ[key] for key in ANTHROPIC_SECRET_ENV_KEYS}
