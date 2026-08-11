from __future__ import annotations

from devices.lucid_do import BinaryValve, LedController


class FakeDigitalOutput:
    def __init__(self) -> None:
        self.states: dict[int, int] = {}
        self.read_count = 0

    def write_channel(self, channel: int, state: int) -> None:
        self.states[channel] = state

    def read_channel(self, channel: int) -> int:
        self.read_count += 1
        return self.states.get(channel, 0)


def test_binary_valve_cached_state_avoids_extra_read() -> None:
    output = FakeDigitalOutput()
    valve = BinaryValve(output, channel=0)

    valve.open()

    assert valve.is_open(refresh=False)
    assert output.read_count == 0
    assert valve.is_open(refresh=True)
    assert output.read_count == 1


def test_led_cached_state_avoids_extra_read() -> None:
    output = FakeDigitalOutput()
    led = LedController(output, channel=1)

    led.on()

    assert led.is_on(refresh=False)
    assert output.read_count == 0
    assert led.is_on(refresh=True)
    assert output.read_count == 1


if __name__ == "__main__":
    test_binary_valve_cached_state_avoids_extra_read()
    test_led_cached_state_avoids_extra_read()
    print("Lucid digital output cache: OK")
