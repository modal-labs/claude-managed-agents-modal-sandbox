from __future__ import annotations

import sys
import termios
import threading
import time
import tty
from collections.abc import Callable
from contextlib import contextmanager

from rich.align import Align
from rich.columns import Columns
from rich.console import Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.pretty import pretty_repr
from rich.text import Text

from cli_app.state import AppState
from cli_app.state import ClaudeState
from cli_app.state import EventBlock
from cli_app.state import ModalState


UI_WIDTH = 100
MAX_EVENT_BODY_LINES = 8
MAX_EVENT_BODY_COLUMNS = UI_WIDTH - 14
STATUS_HEIGHT = 5
INNER_STATUS_HEIGHT = 3
INNER_STATUS_WIDTH = (UI_WIDTH - 4) // 2
GREY_STYLE = "bright_black"
MODAL_MARK = r"""
 /\\ /\\
/ // \ \\
\//   \//
""".strip("\n")


def _link_style(url: str | None) -> str:
    if url:
        return f"link {url} white"
    return "white"


def _sandbox_status_color(status: str) -> str:
    if status == "running":
        return "green"
    if status == "stopped":
        return GREY_STYLE
    return "bright_white"


def render_header() -> Panel:
    details = [
        Text("Maude", style="bold green"),
        Text("Modal Sandboxes + Claude Managed Agents", style="white"),
        Text(
            "** demonstrates the integration and Modal Sandbox features **",
            style=GREY_STYLE,
        ),
    ]
    mark_width = max(len(mark) for mark in MODAL_MARK.splitlines())
    lines: list[Text] = []
    for mark, detail in zip(MODAL_MARK.splitlines(), details, strict=True):
        line = Text()
        line.append(mark.ljust(mark_width), style="bold green")
        line.append("  ")
        line.append_text(detail)
        lines.append(line)
    return Panel(
        Group(*lines),
        border_style="bright_black",
        height=5,
        width=UI_WIDTH,
    )


def _resource_links(resources: list[tuple[str, str | None]]) -> Text:
    body = Text()
    if not resources:
        return Text("None", style=GREY_STYLE)

    for index, (label, url) in enumerate(resources):
        if index:
            body.append(" · ", style=GREY_STYLE)
        body.append(label, style=_link_style(url))
    return body


def render_modal_status(modal: ModalState, *, width: int) -> Panel:
    if not modal.sandbox_id:
        body = _resource_links([])
    else:
        body = Text()
        body.append("Sandbox", style=_link_style(modal.sandbox_url))
        body.append(" is ", style=GREY_STYLE)
        body.append(
            modal.sandbox_status,
            style=_sandbox_status_color(modal.sandbox_status),
        )
    if modal.connection_url:
        body.append(" (", style=GREY_STYLE)
        body.append(":8080", style=_link_style(modal.connection_url))
        body.append(")", style=GREY_STYLE)
    if modal.volume_path:
        body.append(" · ", style=GREY_STYLE)
        body.append("Volume", style=_link_style(modal.volume_url))
    return Panel(
        body,
        title=Text("Modal", style="bold green"),
        border_style="green",
        width=width,
        height=INNER_STATUS_HEIGHT,
    )


def render_claude_status(claude: ClaudeState, *, width: int) -> Panel:
    body = _resource_links(
        [
            ("Agent", claude.agent_url),
            ("Environment", claude.environment_url),
            ("Session", claude.session_url),
        ]
    )
    return Panel(
        body,
        title=Text("Claude", style="bold orange1"),
        border_style="orange1",
        width=width,
        height=INNER_STATUS_HEIGHT,
    )


def render_status_row(state: AppState) -> Panel:
    body = Columns(
        [
            render_claude_status(state.claude, width=INNER_STATUS_WIDTH),
            render_modal_status(state.modal, width=INNER_STATUS_WIDTH),
        ],
        padding=0,
        expand=False,
    )
    return Panel(
        body,
        title=Text("resources", style=GREY_STYLE),
        border_style=GREY_STYLE,
        width=UI_WIDTH,
        height=STATUS_HEIGHT,
    )


def render_events(state: AppState) -> Panel:
    event_panels = [
        Panel(
            _event_body(event),
            title=Text(event.title, style=f"bold {event.style}"),
            border_style=event.style,
        )
        for event in state.events
    ]
    if not event_panels:
        event_panels = [
            Align.center(
                Text(
                    "\nWaiting for events...",
                    style=GREY_STYLE,
                    justify="center",
                ),
                vertical="middle",
            )
        ]

    return Panel(
        Group(*event_panels),
        title=Text("events", style=GREY_STYLE),
        border_style=GREY_STYLE,
        width=UI_WIDTH,
    )


def _event_body(event: EventBlock):
    if event.style == "dim":
        return _truncate_text(str(event.body), style="white")
    if isinstance(event.body, str):
        return _truncate_text(event.body)
    return _truncate_text(pretty_repr(event.body, max_width=MAX_EVENT_BODY_COLUMNS))


def _truncate_text(text: str, *, style: str | None = None) -> Text:
    lines = text.splitlines() or [""]
    if len(lines) <= MAX_EVENT_BODY_LINES:
        return Text("\n".join(_truncate_line(line) for line in lines), style=style)

    hidden_count = len(lines) - MAX_EVENT_BODY_LINES
    visible_lines = [_truncate_line(line) for line in lines[:MAX_EVENT_BODY_LINES]]
    truncated = Text("\n".join(visible_lines), style=style)
    truncated.append(
        f"\n... {hidden_count} more line{'s' if hidden_count != 1 else ''}",
        style=GREY_STYLE,
    )
    return truncated


def _truncate_line(line: str) -> str:
    if len(line) <= MAX_EVENT_BODY_COLUMNS:
        return line
    return f"{line[: MAX_EVENT_BODY_COLUMNS - 3]}..."


def render_input(state: AppState) -> Panel:
    if state.input_enabled:
        body = Text.assemble(("> ", "bold bright_blue"), state.input_text)
    else:
        body = Text("waiting for Claude...", style="dim")
    return Panel(
        body,
        title="input",
        border_style="bright_blue" if state.input_enabled else "bright_black",
        width=UI_WIDTH,
    )


def render(state: AppState) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(render_header(), name="header", size=5),
        Layout(render_status_row(state), name="status", size=STATUS_HEIGHT),
        Layout(render_events(state), name="events", ratio=1),
        Layout(render_input(state), name="input", size=3),
    )
    return layout


@contextmanager
def raw_terminal():
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def start_input_thread(
    state: AppState,
    lock: threading.Lock,
    stop_event: threading.Event,
    on_submit: Callable[[str], None],
) -> threading.Thread:
    def run() -> None:
        while not stop_event.is_set():
            char = sys.stdin.read(1)
            if char in ("\x03", "\x04"):
                with lock:
                    state.running = False
                stop_event.set()
                return

            submit_text: str | None = None
            with lock:
                if not state.input_enabled:
                    continue
                if char in ("\r", "\n"):
                    submit_text = state.input_text.strip()
                    state.input_text = ""
                elif char in ("\x7f", "\b"):
                    state.input_text = state.input_text[:-1]
                elif char == "\x1b":
                    continue
                elif char.isprintable():
                    state.input_text += char

            if submit_text:
                on_submit(submit_text)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def run_live(
    state: AppState,
    lock: threading.Lock,
    stop_event: threading.Event,
    on_submit: Callable[[str], None],
) -> None:
    with raw_terminal():
        start_input_thread(state, lock, stop_event, on_submit)
        with Live(render(state), refresh_per_second=12, screen=True) as live:
            while not stop_event.is_set():
                with lock:
                    if not state.running:
                        stop_event.set()
                        return
                    live.update(render(state))
                time.sleep(0.05)
