from pathlib import Path

import dotenv
import modal

from config import (
    APP_LOG_LEVEL,
    APP_SANDBOX_IDLE_TIMEOUT_SECONDS,
    APP_SANDBOX_REPO_IMAGE_PATH,
    APP_SANDBOX_REPO_URL,
    APP_SANDBOX_REPO_WORKDIR_NAME,
    APP_SANDBOX_WORKDIR,
    EXAMPLE_ROOT,
    MODAL_APP_NAME,
)


_sandbox_entrypoint_src = Path(__file__).parent / "sandbox_entrypoint.py"
_sandbox_entrypoint_dst = "/root/sandbox_entrypoint.py"


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
    .add_local_file(_sandbox_entrypoint_src, _sandbox_entrypoint_dst, copy=True)
    .entrypoint(["python", _sandbox_entrypoint_dst])
    .env(
        {
            "APP_LOG_LEVEL": APP_LOG_LEVEL,
            "APP_SANDBOX_IDLE_TIMEOUT_SECONDS": str(APP_SANDBOX_IDLE_TIMEOUT_SECONDS),
            "APP_SANDBOX_REPO_IMAGE_PATH": APP_SANDBOX_REPO_IMAGE_PATH,
            "APP_SANDBOX_REPO_WORKDIR_NAME": APP_SANDBOX_REPO_WORKDIR_NAME,
            "APP_SANDBOX_WORKDIR": APP_SANDBOX_WORKDIR,
        }
    )
)


app = modal.App(MODAL_APP_NAME)


@app.local_entrypoint()
def main() -> None:
    image_id = sandbox_image.build(app).object_id
    dotenv.set_key(
        EXAMPLE_ROOT / ".env", "SANDBOX_IMAGE_ID", image_id, quote_mode="never"
    )
    print(f"SANDBOX_IMAGE_ID={image_id}")
