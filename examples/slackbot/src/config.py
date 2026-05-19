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

SLACK_SECRET_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AGENT_ID",
    "ANTHROPIC_ENVIRONMENT_ID",
    "ANTHROPIC_WORKSPACE_ID",
    "SLACK_BOT_TOKEN",
    "SLACK_SIGNING_SECRET",
)

MODAL_APP_NAME = "claude-managed-agents-slackbot"
MODAL_SESSIONS_VOLUME_NAME = MODAL_APP_NAME

APP_LOG_LEVEL = "INFO"
APP_SANDBOX_WORKDIR = "/workspace"
APP_SANDBOX_IDLE_TIMEOUT_SECONDS = 60.0
APP_SANDBOX_TIMEOUT_SECONDS = 600
APP_SANDBOX_REPO_URL = "https://github.com/modal-labs/modal-examples.git"
APP_SANDBOX_REPO_IMAGE_PATH = "/opt/modal-examples"
APP_SANDBOX_REPO_WORKDIR_NAME = "modal-examples"

APP_CONFIG_PATH = "/root/config.py"
APP_MODAL_APP_PATH = "/root/modal_app.py"
APP_SANDBOX_TOOL_RUNNER_PATH = "/root/sandbox_tool_runner.py"
APP_PYPROJECT_TOML_PATH = "/root/pyproject.toml"
APP_UV_LOCK_PATH = "/root/uv.lock"
APP_AGENT_BRIDGE_PATH = "/root/agent_bridge.py"
APP_SESSION_STORE_PATH = "/root/session_store.py"

SLACK_SESSIONS_DICT_NAME = "claude-managed-agents-slackbot-sessions"
SLACK_EVENTS_DICT_NAME = "claude-managed-agents-slackbot-events"


def anthropic_secret_env() -> dict[str, str]:
    return {key: os.environ[key] for key in ANTHROPIC_SECRET_ENV_KEYS}


def slack_secret_env() -> dict[str, str]:
    return {key: os.environ[key] for key in SLACK_SECRET_ENV_KEYS}
