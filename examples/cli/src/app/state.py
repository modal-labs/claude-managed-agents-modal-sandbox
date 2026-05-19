from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from dataclasses import field
from typing import Any


MAX_EVENTS = 8


@dataclass
class EventBlock:
    title: str
    body: Any
    style: str


@dataclass
class ModalState:
    sandbox_status: str = "waiting"
    sandbox_id: str | None = None
    sandbox_url: str | None = None
    connection_url: str | None = None
    volume_path: str | None = None
    volume_url: str | None = None


@dataclass
class ClaudeState:
    agent_id: str
    environment_id: str
    session_id: str
    agent_url: str | None = None
    environment_url: str | None = None
    session_url: str | None = None


@dataclass
class AppState:
    claude: ClaudeState
    events: deque[EventBlock] = field(default_factory=deque)
    input_text: str = ""
    input_enabled: bool = False
    modal: ModalState = field(default_factory=ModalState)
    running: bool = True


def append_event(state: AppState, event: EventBlock) -> None:
    state.events.append(event)
    while len(state.events) > MAX_EVENTS:
        state.events.popleft()


def append_events(state: AppState, events: list[EventBlock]) -> None:
    for event in events:
        append_event(state, event)
