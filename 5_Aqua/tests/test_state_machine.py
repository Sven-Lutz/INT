from control.state_machine import (
    ProcessState,
    ProcessStateMachine,
)


def main() -> None:
    state_machine = ProcessStateMachine()

    assert state_machine.state == ProcessState.DISCONNECTED

    state_machine.mark_ready()
    assert state_machine.state == ProcessState.READY

    state_machine.mark_running()
    assert state_machine.state == ProcessState.RUNNING

    state_machine.mark_stopping()
    assert state_machine.state == ProcessState.STOPPING

    state_machine.mark_stopped()
    assert state_machine.state == ProcessState.STOPPED

    print("State-machine test passed.")


if __name__ == "__main__":
    main()
