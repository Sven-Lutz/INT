from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from threading import Lock


class ProcessState(Enum):
    DISCONNECTED = auto()
    READY = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    FAULT = auto()


class InvalidStateTransitionError(RuntimeError):
    """Raised when an invalid state transition is requested."""


@dataclass(frozen=True)
class StateTransition:
    previous_state: ProcessState
    new_state: ProcessState
    reason: str


class ProcessStateMachine:
    _ALLOWED_TRANSITIONS = {
        ProcessState.DISCONNECTED: {
            ProcessState.READY,
            ProcessState.FAULT,
        },
        ProcessState.READY: {
            ProcessState.RUNNING,
            ProcessState.DISCONNECTED,
            ProcessState.STOPPED,
            ProcessState.FAULT,
        },
        ProcessState.RUNNING: {
            ProcessState.STOPPING,
            ProcessState.FAULT,
        },
        ProcessState.STOPPING: {
            ProcessState.STOPPED,
            ProcessState.FAULT,
        },
        ProcessState.STOPPED: {
            ProcessState.READY,
            ProcessState.DISCONNECTED,
            ProcessState.RUNNING,
            ProcessState.FAULT,
        },
        ProcessState.FAULT: {
            ProcessState.STOPPING,
            ProcessState.STOPPED,
            ProcessState.DISCONNECTED,
            ProcessState.READY,
        },
    }

    def __init__(self) -> None:
        self._state = ProcessState.DISCONNECTED
        self._fault_message: str | None = None
        self._last_transition: StateTransition | None = None
        self._lock = Lock()

    @property
    def state(self) -> ProcessState:
        with self._lock:
            return self._state

    @property
    def state_name(self) -> str:
        return self.state.name

    @property
    def fault_message(self) -> str | None:
        with self._lock:
            return self._fault_message

    @property
    def last_transition(self) -> StateTransition | None:
        with self._lock:
            return self._last_transition

    @property
    def is_ready(self) -> bool:
        return self.state == ProcessState.READY

    @property
    def is_running(self) -> bool:
        return self.state == ProcessState.RUNNING

    def transition_to(
        self,
        new_state: ProcessState,
        *,
        reason: str = "",
    ) -> StateTransition:
        with self._lock:
            previous_state = self._state

            if new_state == previous_state:
                raise InvalidStateTransitionError(
                    f"Process is already in state {new_state.name}."
                )

            if (
                new_state
                not in self._ALLOWED_TRANSITIONS[previous_state]
            ):
                raise InvalidStateTransitionError(
                    f"Invalid state transition: "
                    f"{previous_state.name} -> {new_state.name}."
                )

            self._state = new_state

            if new_state != ProcessState.FAULT:
                self._fault_message = None

            transition = StateTransition(
                previous_state=previous_state,
                new_state=new_state,
                reason=reason,
            )
            self._last_transition = transition
            return transition

    def mark_ready(self, reason: str = "") -> StateTransition:
        return self.transition_to(
            ProcessState.READY,
            reason=reason,
        )

    def mark_running(self, reason: str = "") -> StateTransition:
        return self.transition_to(
            ProcessState.RUNNING,
            reason=reason,
        )

    def mark_stopping(self, reason: str = "") -> StateTransition:
        return self.transition_to(
            ProcessState.STOPPING,
            reason=reason,
        )

    def mark_stopped(self, reason: str = "") -> StateTransition:
        return self.transition_to(
            ProcessState.STOPPED,
            reason=reason,
        )

    def mark_disconnected(self, reason: str = "") -> StateTransition:
        return self.transition_to(
            ProcessState.DISCONNECTED,
            reason=reason,
        )

    def mark_fault(self, message: str) -> StateTransition:
        if not message:
            raise ValueError(
                "Fault message must not be empty."
            )

        with self._lock:
            previous_state = self._state
            self._state = ProcessState.FAULT
            self._fault_message = message

            transition = StateTransition(
                previous_state=previous_state,
                new_state=ProcessState.FAULT,
                reason=message,
            )
            self._last_transition = transition
            return transition
