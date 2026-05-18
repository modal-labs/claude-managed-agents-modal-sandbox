import argparse
import os
import shutil
import threading
from collections.abc import Sequence
from dataclasses import dataclass

import anthropic
from rich.console import Console
from rich.panel import Panel
from rich.pretty import Pretty
from rich.text import Text

from config import load_env


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
console = Console()
USER_PROMPT = "user: "
MODAL_MARK = r"""
 /\\ /\\ 
/ // \ \\
\//   \//
""".strip("\n")


@dataclass
class PendingUserMessage:
    text: str
    consumed: bool = False


def _text_content(blocks: list[object] | None) -> str:
    if not blocks:
        return ""
    return "\n\n".join(
        block.text for block in blocks if getattr(block, "type", None) == "text"
    )


def _event_context(event_data: dict[str, object]) -> str:
    keys = ("id", "session_thread_id", "tool_use_id", "mcp_tool_use_id")
    parts = [f"{key}={value}" for key in keys if (value := event_data.get(key))]
    return f" {' '.join(parts)}" if parts else ""


def _print_banner() -> None:
    details = [
        Text("Maude", style="bold bright_green"),
        Text(""),
        Text("Modal Sandboxes + Claude Managed Agents", style="bright_white"),
    ]
    for mark, detail in zip(MODAL_MARK.splitlines(), details, strict=True):
        line = Text(mark, style="bold bright_green")
        line.append("  ")
        line.append_text(detail)
        console.print(line)
    console.print()


def _resume_command(session_id: str) -> str:
    return f"uv run src/cli.py --resume {session_id}"


def _print_resume_hint(session_id: str) -> None:
    console.print(
        f"[dim]Resume later:[/dim] [cyan]{_resume_command(session_id)}[/cyan]"
    )


def _clear_input_line(text: str) -> None:
    if not console.is_terminal:
        return
    width = max(shutil.get_terminal_size(fallback=(80, 24)).columns, 1)
    line_count = max((len(USER_PROMPT) + len(text) - 1) // width + 1, 1)
    console.file.write("\x1b[1A\x1b[2K" * line_count)
    console.file.flush()


def _send_user_message(
    client: anthropic.Anthropic,
    session_id: str,
    prompt: str,
) -> None:
    client.beta.sessions.events.send(
        session_id,
        events=[
            {"type": "user.message", "content": [{"type": "text", "text": prompt}]}
        ],
    )


def _event_id(event: object) -> str | None:
    value = getattr(event, "id", None)
    if isinstance(value, str):
        return value
    if hasattr(event, "to_dict"):
        event_data = event.to_dict(mode="json")
        value = event_data.get("id")
        return value if isinstance(value, str) else None
    return None


def _render_event(event: object) -> None:
    event_type = event.type
    if event_type in USER_EVENT_TYPES:
        event_data = event.to_dict(mode="json")
        body = _text_content(getattr(event, "content", None)) or event_data
        console.print(
            Panel(
                body if isinstance(body, str) else Pretty(body),
                title=Text("user.message", style="bold bright_blue"),
                border_style="bright_blue",
                style="bright_white",
                title_align="left",
            )
        )
    elif event_type == "agent.message":
        for block in event.content:
            if block.type == "text":
                console.print(
                    Panel(
                        block.text,
                        title=Text("agent.message", style="bold bright_green"),
                        border_style="bright_green",
                        style="bright_white",
                        title_align="left",
                    )
                )
    elif event_type in TOOL_EVENT_TYPES:
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
            is_error = event_data.get("is_error")
            title = f"{event_type}: error={is_error}{event_context}"

        console.print(
            Panel(
                body if isinstance(body, str) else Pretty(body),
                title=Text(title, style="dim"),
                border_style="bright_black",
                style="dim",
                title_align="left",
            )
        )


def _render_user_text(text: str) -> None:
    console.print(
        Panel(
            text,
            title=Text("user.message", style="bold bright_blue"),
            border_style="bright_blue",
            style="bright_white",
            title_align="left",
        )
    )


def _is_matching_user_message(event: object, pending: PendingUserMessage) -> bool:
    if event.type not in USER_EVENT_TYPES:
        return False
    text = _text_content(getattr(event, "content", None))
    return text.strip() == pending.text.strip()


def _replay_events(
    client: anthropic.Anthropic,
    session_id: str,
) -> tuple[set[str], bool]:
    seen_event_ids: set[str] = set()
    input_ready = False
    waiting_for_agent_message = False
    agent_message_seen = False
    events = client.beta.sessions.events.list(session_id, order="asc")
    for event in events:
        if event_id := _event_id(event):
            seen_event_ids.add(event_id)
        _render_event(event)
        if event.type in SESSION_RUNNING_EVENT_TYPES:
            input_ready = False
            waiting_for_agent_message = False
            agent_message_seen = False
        elif event.type == "agent.message":
            agent_message_seen = True
            if waiting_for_agent_message:
                input_ready = True
                waiting_for_agent_message = False
        elif event.type in SESSION_READY_EVENT_TYPES:
            if agent_message_seen:
                input_ready = True
            else:
                waiting_for_agent_message = True
    return seen_event_ids, input_ready


def _stream_events(
    client: anthropic.Anthropic,
    session_id: str,
    input_ready: threading.Event,
    pending_user_messages: list[PendingUserMessage],
    pending_lock: threading.Lock,
    *,
    seen_event_ids: set[str] | None = None,
) -> None:
    seen_event_ids = seen_event_ids or set()
    waiting_for_agent_message = False
    agent_message_seen = False
    with client.beta.sessions.events.stream(session_id) as stream:
        for event in stream:
            event_id = _event_id(event)
            if event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            with pending_lock:
                for pending in pending_user_messages:
                    if (
                        not pending.consumed
                        and _is_matching_user_message(event, pending)
                    ):
                        pending.consumed = True
                        break
                else:
                    pending = None
            if pending is not None:
                continue
            _render_event(event)
            if event.type in SESSION_RUNNING_EVENT_TYPES:
                input_ready.clear()
                waiting_for_agent_message = False
                agent_message_seen = False
            elif event.type == "agent.message":
                agent_message_seen = True
                if waiting_for_agent_message:
                    input_ready.set()
                    waiting_for_agent_message = False
            elif event.type in SESSION_READY_EVENT_TYPES:
                if agent_message_seen:
                    input_ready.set()
                else:
                    waiting_for_agent_message = True


def _start_stream_thread(
    session_id: str,
    seen_event_ids: set[str],
    input_ready: threading.Event,
    pending_user_messages: list[PendingUserMessage],
    pending_lock: threading.Lock,
) -> threading.Thread:
    def run() -> None:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        try:
            _stream_events(
                client,
                session_id,
                input_ready,
                pending_user_messages,
                pending_lock,
                seen_event_ids=seen_event_ids,
            )
        except Exception as e:
            console.print(f"[red]Stream stopped: {type(e).__name__}: {e}[/red]")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _interactive_loop(
    client: anthropic.Anthropic,
    session_id: str,
    input_ready: threading.Event,
    pending_user_messages: list[PendingUserMessage],
    pending_lock: threading.Lock,
) -> None:
    while True:
        input_ready.wait()
        try:
            prompt = console.input(
                f"[bold bright_blue]{USER_PROMPT}[/bold bright_blue]"
            )
        except (EOFError, KeyboardInterrupt):
            console.print()
            _print_resume_hint(session_id)
            return

        _clear_input_line(prompt)
        prompt = prompt.strip()
        if not prompt:
            continue

        input_ready.clear()
        _render_user_text(prompt)
        with pending_lock:
            pending_user_messages.append(PendingUserMessage(prompt))
        _send_user_message(client, session_id, prompt)


def main(*, resume_session_id: str | None = None) -> None:
    load_env()
    _print_banner()
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if resume_session_id:
        session_id = resume_session_id
        seen_event_ids, ready_from_history = _replay_events(client, session_id)
        initial_input_ready = ready_from_history
    else:
        session = client.beta.sessions.create(
            agent=os.environ["ANTHROPIC_AGENT_ID"],
            environment_id=os.environ["ANTHROPIC_ENVIRONMENT_ID"],
        )
        session_id = session.id
        seen_event_ids, ready_from_history = _replay_events(client, session_id)
        initial_input_ready = ready_from_history or not seen_event_ids

    input_ready = threading.Event()
    if initial_input_ready:
        input_ready.set()
    pending_user_messages: list[PendingUserMessage] = []
    pending_lock = threading.Lock()

    try:
        _start_stream_thread(
            session_id,
            seen_event_ids,
            input_ready,
            pending_user_messages,
            pending_lock,
        )
        _interactive_loop(
            client,
            session_id,
            input_ready,
            pending_user_messages,
            pending_lock,
        )
    except KeyboardInterrupt:
        console.print()
        _print_resume_hint(session_id)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open an interactive Claude Managed Agents session."
    )
    parser.add_argument(
        "--resume",
        metavar="SESSION_ID",
        help=(
            "Resume an existing session by ID, replay persisted events, then stream "
            "live events."
        ),
    )
    return parser.parse_args(argv)


def cli(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    main(resume_session_id=args.resume)


if __name__ == "__main__":
    cli()
