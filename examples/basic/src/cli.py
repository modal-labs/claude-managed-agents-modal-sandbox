from __future__ import annotations

import argparse
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import Console

from cli_app.agent_runtime import AgentRuntime
from cli_app.live_ui import run_live
from cli_app.sandbox_runtime import SandboxRuntime
from cli_app.sandbox_runtime import wait_for_next_poll
from cli_app.state import AppState
from cli_app.state import ClaudeState
from cli_app.state import EventBlock
from cli_app.state import ModalState
from cli_app.state import append_event
from cli_app.state import append_events
from config import load_env


console = Console()


@dataclass
class PendingUserMessage:
    text: str
    consumed: bool = False


def _resume_command(session_id: str) -> str:
    return f"uv run src/cli.py --resume {session_id}"


def _print_resume_hint(session_id: str) -> None:
    console.print(
        f"[dim]Resume later:[/dim] [cyan]{_resume_command(session_id)}[/cyan]"
    )


def _is_matching_pending(
    user_text: str | None,
    pending_user_messages: list[PendingUserMessage],
) -> bool:
    if user_text is None:
        return False
    for pending in pending_user_messages:
        if not pending.consumed and user_text.strip() == pending.text.strip():
            pending.consumed = True
            return True
    return False


def _start_event_stream_thread(
    *,
    runtime: AgentRuntime,
    session_id: str,
    seen_event_ids: set[str],
    state: AppState,
    lock: threading.Lock,
    stop_event: threading.Event,
    pending_user_messages: list[PendingUserMessage],
) -> threading.Thread:
    def run() -> None:
        try:
            for update in runtime.stream_events(
                session_id=session_id,
                seen_event_ids=seen_event_ids,
            ):
                if stop_event.is_set():
                    return
                with lock:
                    if not _is_matching_pending(
                        update.user_text,
                        pending_user_messages,
                    ):
                        append_events(state, update.blocks)
                    if update.input_ready is not None:
                        state.input_enabled = update.input_ready
        except Exception as exc:
            with lock:
                append_event(
                    state,
                    EventBlock(
                        "stream.error",
                        f"{type(exc).__name__}: {exc}",
                        "red",
                    ),
                )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def _modal_state_from_running_snapshot(snapshot) -> ModalState:
    return ModalState(
        sandbox_status="running",
        sandbox_id=snapshot.sandbox_id,
        sandbox_url=snapshot.sandbox_url,
        connection_url=snapshot.connection_url,
        volume_path=snapshot.volume_path,
        volume_url=snapshot.volume_url,
    )


def _start_sandbox_monitor_thread(
    *,
    runtime: SandboxRuntime,
    session_id: str,
    state: AppState,
    lock: threading.Lock,
    stop_event: threading.Event,
    preview: bool,
) -> threading.Thread:
    def run() -> None:
        current_sandbox_id: str | None = None
        connection_url_sandbox_id: str | None = None

        while not stop_event.is_set():
            try:
                snapshot = runtime.snapshot(
                    session_id,
                    create_connection_url=preview,
                )
            except Exception:
                if wait_for_next_poll(stop_event):
                    return
                continue

            with lock:
                if snapshot.sandbox_id is None:
                    if current_sandbox_id is not None:
                        state.modal.sandbox_status = "stopped"
                        state.modal.connection_url = None
                        append_event(
                            state,
                            EventBlock(
                                "sandbox.stopped",
                                f"Sandbox {current_sandbox_id} stopped or expired.",
                                "green",
                            ),
                        )
                        current_sandbox_id = None
                        connection_url_sandbox_id = None
                    elif state.modal.sandbox_id is None:
                        state.modal = ModalState()
                elif snapshot.sandbox_id != current_sandbox_id:
                    if current_sandbox_id is not None:
                        append_event(
                            state,
                            EventBlock(
                                "sandbox.stopped",
                                f"Sandbox {current_sandbox_id} stopped or expired.",
                                "green",
                            ),
                        )
                    current_sandbox_id = snapshot.sandbox_id
                    connection_url_sandbox_id = None
                    state.modal = _modal_state_from_running_snapshot(snapshot)
                    append_event(
                        state,
                        EventBlock(
                            "sandbox.started",
                            f"Sandbox {snapshot.sandbox_id} is running.",
                            "green",
                        ),
                    )
                else:
                    state.modal = _modal_state_from_running_snapshot(snapshot)

                if (
                    snapshot.connection_url
                    and snapshot.sandbox_id != connection_url_sandbox_id
                ):
                    append_event(
                        state,
                        EventBlock(
                            "sandbox.preview",
                            "Secure Connection URL to port 8080 of Sandbox",
                            "green",
                        ),
                    )
                    connection_url_sandbox_id = snapshot.sandbox_id

            if wait_for_next_poll(stop_event):
                return

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def main(
    *,
    resume_session_id: str | None = None,
    preview: bool = True,
) -> None:
    load_env()
    agent_runtime = AgentRuntime.from_env()
    sandbox_runtime = SandboxRuntime()

    replay = agent_runtime.start_session(resume_session_id=resume_session_id)
    state = AppState(
        claude=ClaudeState(
            agent_id=replay.agent_id,
            agent_url=replay.agent_url,
            environment_id=replay.environment_id,
            environment_url=replay.environment_url,
            session_id=replay.session_id,
            session_url=replay.session_url,
        ),
        input_enabled=replay.input_ready,
    )
    append_events(state, replay.blocks)

    lock = threading.Lock()
    stop_event = threading.Event()
    pending_user_messages: list[PendingUserMessage] = []

    def submit_user_message(text: str) -> None:
        with lock:
            append_event(state, EventBlock("user.message", text, "bright_blue"))
            state.input_enabled = False
            state.input_text = ""
            pending_user_messages.append(PendingUserMessage(text))
        try:
            agent_runtime.send_user_message(session_id=replay.session_id, text=text)
        except Exception as exc:
            with lock:
                append_event(
                    state,
                    EventBlock(
                        "send.error",
                        f"{type(exc).__name__}: {exc}",
                        "red",
                    ),
                )
                state.input_enabled = True

    try:
        _start_event_stream_thread(
            runtime=agent_runtime,
            session_id=replay.session_id,
            seen_event_ids=replay.seen_event_ids,
            state=state,
            lock=lock,
            stop_event=stop_event,
            pending_user_messages=pending_user_messages,
        )
        _start_sandbox_monitor_thread(
            runtime=sandbox_runtime,
            session_id=replay.session_id,
            state=state,
            lock=lock,
            stop_event=stop_event,
            preview=preview,
        )
        run_live(state, lock, stop_event, submit_user_message)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        _print_resume_hint(replay.session_id)


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
    parser.add_argument(
        "--no-preview",
        dest="preview",
        action="store_false",
        help="Disable clickable Modal Sandbox preview URLs for port 8080.",
    )
    parser.set_defaults(preview=True)
    return parser.parse_args(argv)


def cli(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    main(
        resume_session_id=args.resume,
        preview=args.preview,
    )


if __name__ == "__main__":
    cli()
