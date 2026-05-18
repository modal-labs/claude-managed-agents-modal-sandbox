from modal_app import app

# Import modules for Modal side effects: each module registers functions on app.
import claude_webhook_handler  # noqa: F401
import slack_webhook  # noqa: F401


__all__ = ["app"]
