# hardware/drivers/rly02.py
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from struct import unpack
from threading import Lock
from typing import Optional

import serial

# rly02 command mapping (single-byte protocol)
COMMANDS = {
    "relay_1_on": 0x65,
    "relay_1_off": 0x6F,
    "relay_2_on": 0x66,
    "relay_2_off": 0x70,
    "info": 0x5A,
    "relay_states": 0x5B,
}


@dataclass(frozen=True)
class Rly02Config:
    port: str = "COM6"
    baudrate: int = 9600
    timeout_s: float = 1.0

    # Quality-of-life hardening:
    open_settle_s: float = 0.03          # let USB-serial settle after open
    retries: int = 1                      # transient IO retries
    retry_sleep_s: float = 0.05           # sleep between retries


class Rly02:
    """
    RLY02 relay controller (single-byte protocol).

    Notes:
    - Supports both "stateless" usage (open per command) and "persistent" usage via connect()/close().
    - Thread-safe: internal lock around serial transactions.
    """

    def __init__(self, cfg: Rly02Config = Rly02Config()):
        self.cfg = cfg
        self._ser: Optional[serial.Serial] = None
        self._lock = Lock()

        if not str(self.cfg.port).strip():
            raise ValueError("Rly02Config.port must be set.")
        if int(self.cfg.baudrate) <= 0:
            raise ValueError("Rly02Config.baudrate must be > 0.")
        if float(self.cfg.timeout_s) <= 0:
            raise ValueError("Rly02Config.timeout_s must be > 0.")
        if int(self.cfg.retries) < 0:
            raise ValueError("Rly02Config.retries must be >= 0.")

    # ---------- connection (optional persistent mode) ----------
    def connect(self) -> None:
        if self._ser is not None and self._ser.is_open:
            return

        ser = serial.Serial(self.cfg.port, self.cfg.baudrate, timeout=self.cfg.timeout_s)
        # Best-effort: clear junk
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        self._ser = ser
        time.sleep(float(self.cfg.open_settle_s))

    def close(self) -> None:
        if self._ser is None:
            return
        try:
            self._ser.close()
        finally:
            self._ser = None

    def __enter__(self) -> "Rly02":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------- internal IO ----------
    def _send(self, cmd: int, *, read_n: int = 0) -> Optional[bytes]:
        """
        Send one-byte command and optionally read exactly read_n bytes.
        If not connected in persistent mode, opens/closes the port for this transaction.
        """
        def _tx(ser: serial.Serial) -> Optional[bytes]:
            # Clear stale bytes before request (best-effort)
            try:
                ser.reset_input_buffer()
            except Exception:
                pass

            ser.write(bytes([int(cmd) & 0xFF]))
            try:
                ser.flush()
            except Exception:
                pass

            if read_n <= 0:
                return None

            data = ser.read(int(read_n))
            if data is None:
                return None
            if len(data) != int(read_n):
                raise RuntimeError(f"No/partial response from rly02 (wanted={read_n}, got={len(data)})")
            return data

        with self._lock:
            last_exc: Optional[Exception] = None

            for attempt in range(self.cfg.retries + 1):
                try:
                    if self._ser is not None and self._ser.is_open:
                        return _tx(self._ser)

                    # Stateless mode: open per transaction
                    with serial.Serial(self.cfg.port, self.cfg.baudrate, timeout=self.cfg.timeout_s) as ser:
                        try:
                            ser.reset_input_buffer()
                            ser.reset_output_buffer()
                        except Exception:
                            pass
                        time.sleep(float(self.cfg.open_settle_s))
                        return _tx(ser)

                except Exception as e:
                    last_exc = e
                    if attempt < self.cfg.retries:
                        time.sleep(float(self.cfg.retry_sleep_s))

            assert last_exc is not None
            raise last_exc

    # ---- relay control ----
    def relay_on(self, relay: int) -> None:
        r = int(relay)
        if r == 1:
            self._send(COMMANDS["relay_1_on"])
            return
        if r == 2:
            self._send(COMMANDS["relay_2_on"])
            return
        raise ValueError("relay must be 1 or 2")

    def relay_off(self, relay: int) -> None:
        r = int(relay)
        if r == 1:
            self._send(COMMANDS["relay_1_off"])
            return
        if r == 2:
            self._send(COMMANDS["relay_2_off"])
            return
        raise ValueError("relay must be 1 or 2")

    def relay_click(self, relay: int, *, seconds: float = 1.0) -> None:
        self.relay_on(relay)
        time.sleep(float(seconds))
        self.relay_off(relay)

    def get_states(self) -> dict:
        raw = self._send(COMMANDS["relay_states"], read_n=1)
        if not raw or len(raw) != 1:
            raise RuntimeError("No response from rly02 for relay_states")

        # Use unsigned byte (0..255); safer than signed 'b'
        code = unpack("B", raw)[0]
        states = {
            0: {"1": False, "2": False},
            1: {"1": True, "2": False},
            2: {"1": False, "2": True},
            3: {"1": True, "2": True},
        }
        if code not in states:
            raise RuntimeError(f"Unexpected relay state code: {code}")
        return states[code]


def _build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="rly02 relay controller")
    p.add_argument("--port", default="COM6")
    p.add_argument("--baudrate", type=int, default=9600)
    p.add_argument("--timeout", type=float, default=1.0)

    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("-s", "--states", action="store_true", help="read relay states")
    g.add_argument("-i", "--info", action="store_true", help="request device info (if supported)")
    g.add_argument("-r", "--relay", type=int, choices=[1, 2], help="relay number (1 or 2)")

    p.add_argument("-a", "--action", choices=["on", "off", "click"], help="relay action (requires --relay)")
    p.add_argument("--click-seconds", type=float, default=1.0, help="click duration in seconds")
    return p


def main() -> int:
    args = _build_cli().parse_args()
    dev = Rly02(Rly02Config(port=args.port, baudrate=args.baudrate, timeout_s=args.timeout))

    if args.states:
        print(dev.get_states())
        return 0

    if args.info:
        resp = dev._send(COMMANDS["info"], read_n=1)
        print(resp if resp is not None else b"")
        return 0

    if args.relay is None or args.action is None:
        raise SystemExit("For relay control, you must provide both --relay and --action")

    if args.action == "on":
        dev.relay_on(args.relay)
    elif args.action == "off":
        dev.relay_off(args.relay)
    else:
        dev.relay_click(args.relay, seconds=args.click_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
