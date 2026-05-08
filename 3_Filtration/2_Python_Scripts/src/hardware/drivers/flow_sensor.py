# src/hardware/drivers/flow_sensor.py
from __future__ import annotations

import logging
import struct
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import serial  # pyserial — always available

try:
    import propar as _propar_lib
except ImportError:
    _propar_lib = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class _ProParSerial:
    """
    Minimal Bronkhorst ProPar ASCII protocol over raw pyserial.

    Implements only what FlowSensor needs: probing for the correct read
    format during connect, then reading that format on every poll.

    Wire format (no spaces):
      Request:  :{len:02X}{node:02X}04{proc:02X}{parm:02X}{type:02X}\\r
      Response: :{len:02X}{node:02X}02{proc:02X}{parm:02X}{type:02X}{data...}\\r

    cmd=0x02 = DATA response (wanted)
    cmd=0x04 = echo of our own request on RS-485 half-duplex bus (skip)
    cmd=0x00 = STATUS/ERROR response (Bronkhorst FlowBus error frame — not data)
    """

    def __init__(self, port: str, baudrate: int, address: int, timeout: float = 1.5):
        self._ser = serial.Serial(
            port, baudrate=baudrate, timeout=timeout,
            bytesize=8, parity="N", stopbits=1,
        )
        self._addr = address & 0xFF
        self._lock = threading.Lock()

    def _query(self, proc: int, ptype: int, parm: int) -> Optional[bytes]:
        """Send one ProPar read request; return the data payload of the cmd=0x02 answer.

        Bronkhorst ProPar ASCII frame layout:
          :{len:02X}{addr:02X}04{proc:02X}{parm:02X}{type:02X}\\r
        Parm comes before type.  Response mirrors this order with cmd=0x02.
        """
        with self._lock:
            payload = bytes([self._addr, 0x04, proc & 0xFF, parm & 0xFF, ptype & 0xFF])
            frame = f":{len(payload):02X}" + payload.hex().upper() + "\r"
            logger.debug(f"ProPar TX: {frame.strip()!r}")
            self._ser.reset_input_buffer()
            self._ser.write(frame.encode("ascii"))

            for attempt in range(4):
                resp = self._ser.readline()
                logger.debug(f"ProPar RX[{attempt}]: {resp!r}")
                if not resp or resp[0:1] != b":":
                    continue
                hex_body = resp[1:].decode("ascii", errors="ignore").replace(" ", "").strip()
                try:
                    raw = bytes.fromhex(hex_body)
                except ValueError:
                    logger.debug(f"ProPar RX[{attempt}]: hex decode failed on {hex_body!r}")
                    continue

                if len(raw) < 3:
                    continue

                cmd = raw[2]
                if cmd == 0x02 and len(raw) >= 6:
                    # Standard DATA answer: [len, node, 0x02, proc, type, parm, data...]
                    return raw[6:]
                if cmd == 0x04:
                    # RS-485 half-duplex echo of our own request — skip and keep reading
                    continue
                if cmd == 0x00:
                    # STATUS/ERROR frame (Bronkhorst FlowBus error, e.g. status=0x22
                    # means "process alarm + slave error").  Not measurement data.
                    logger.debug(
                        f"ProPar: cmd=0x00 ERROR frame received "
                        f"(status={raw[3:].hex() if len(raw) > 3 else '?'})"
                        f" — request (proc={proc:#04x}, type={ptype:#04x}, parm={parm}) rejected by device"
                    )
                    return None  # this format is unsupported; signal probe failure

        return None

    def probe(self, candidates: list[Tuple[int, int, int]]) -> Optional[Tuple[int, int, int]]:
        """
        Try each (proc, ptype, parm) candidate in order.
        Return the first one that produces a cmd=0x02 DATA response, or None.
        """
        for proc, ptype, parm in candidates:
            logger.info(
                f"ProPar probe: trying proc={proc:#04x} type={ptype:#04x} parm={parm}"
            )
            data = self._query(proc, ptype, parm)
            if data is not None:
                logger.info(
                    f"ProPar probe: SUCCESS with proc={proc:#04x} type={ptype:#04x} parm={parm}"
                    f" — data={data.hex()}"
                )
                return (proc, ptype, parm)
        return None

    def read(self, proc: int, ptype: int, parm: int) -> Optional[bytes]:
        """Return raw data bytes from a confirmed working (proc, ptype, parm)."""
        return self._query(proc, ptype, parm)

    def close(self) -> None:
        if self._ser and self._ser.is_open:
            self._ser.close()


@dataclass(frozen=True)
class FlowSensorConfig:
    port: str = "COM5"
    baudrate: int = 38400
    address: int = 3

    proc_nr: int = 33
    parm_nr: int = 0

    scale_mode: str = "engineering"
    full_scale_raw: float = 32000.0
    full_scale_ml_min: float = 150.0

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FlowSensorConfig":
        logger.info(f"FlowSensorConfig.from_dict received: {d}")
        if "flow" in d and isinstance(d["flow"], dict):
            d = d["flow"]

        port = d.get("port", d.get("COM Port", "COM5"))
        baudrate = int(d.get("baudrate", 38400))
        address = int(d.get("address", 3))

        meas = d.get("meas", [33, 0])
        proc_nr = int(meas[0])
        parm_nr = int(meas[1])

        scale_mode = str(d.get("scale_mode", "engineering")).strip().lower()
        fs_raw = float(d.get("full_scale_raw", 32000.0))
        fs_ml = float(d.get("full_scale_ml_min", 150.0))

        return FlowSensorConfig(
            port=port, baudrate=baudrate, address=address,
            proc_nr=proc_nr, parm_nr=parm_nr,
            scale_mode=scale_mode, full_scale_raw=fs_raw, full_scale_ml_min=fs_ml,
        )


class FlowSensor:
    """
    Bronkhorst ES-FLOW / ProPar sensor driver with layered fallback.

    Connection strategy (tried in order):
      1. propar 1.x  — propar.instrument()
      2. propar 0.x  — propar.master() / propar.Master()
      3. Raw pyserial — _ProParSerial (ProPar ASCII, no external library)
    """

    def __init__(self, cfg: FlowSensorConfig | Dict[str, Any]):
        if isinstance(cfg, dict):
            self.cfg = FlowSensorConfig.from_dict(cfg)
        else:
            self.cfg = cfg

        self.flow_sensor: Any = None
        self._cached_parameter_id: int = 0  # propar path: 205=fMeasure(float), 8=Measure(raw)
        self._serial_fmt: Optional[Tuple[int, int, int]] = None  # pyserial path: (proc, ptype, parm)
        self._last_good_flow: float = 0.0
        self._error_count: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_propar_lib(port: str, baudrate: int, address: int) -> Any:
        """Return a propar instrument object, or None if propar is unusable."""
        lib = _propar_lib
        if lib is None:
            return None

        if callable(getattr(lib, "instrument", None)):
            return lib.instrument(port, baudrate=baudrate, address=address)

        if callable(getattr(lib, "master", None)):
            m = lib.master(port, baudrate=baudrate)
            nodes = m.get_nodes()
            for node in nodes:
                if getattr(node, "address", None) == address:
                    return node
            if nodes:
                return nodes[0]

        if callable(getattr(lib, "Master", None)):
            m = lib.Master(port, baudrate=baudrate)
            nodes = m.get_nodes() if hasattr(m, "get_nodes") else []
            for node in nodes:
                if getattr(node, "address", None) == address:
                    return node
            if nodes:
                return nodes[0]

        public_api = [a for a in dir(lib) if not a.startswith("_")]
        logger.warning(
            f"propar library present but has no usable entry point. "
            f"Public API: {public_api}. Falling back to raw pyserial."
        )
        return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self.flow_sensor is not None:
            return
        logger.info(
            f"FlowSensor: connecting to {self.cfg.port} "
            f"(Baud: {self.cfg.baudrate}, Node: {self.cfg.address})"
        )

        try:
            instr = self._try_propar_lib(self.cfg.port, self.cfg.baudrate, self.cfg.address)

            if instr is not None:
                self._connect_via_propar(instr)
            else:
                self._connect_via_serial()

        except Exception as e:
            logger.error(f"FlowSensor: connection failed on {self.cfg.port} -> {e}")
            self.flow_sensor = None

    def _connect_via_propar(self, instr: Any) -> None:
        user_tag = instr.readParameter(115)
        if user_tag is None:
            logger.error(f"FlowSensor: no response on address {self.cfg.address} (propar)")
            return

        logger.info(f"FlowSensor: ping OK via propar, device: '{user_tag}'")

        val_float = instr.readParameter(205)
        if val_float is not None:
            logger.info("FlowSensor: fMeasure (ID 205) OK — using engineering units.")
            self._cached_parameter_id = 205
            object.__setattr__(self.cfg, "scale_mode", "engineering")
        else:
            val_raw = instr.readParameter(8)
            if val_raw is not None:
                logger.info("FlowSensor: Measure (ID 8) OK — using raw scaling.")
                self._cached_parameter_id = 8
                object.__setattr__(self.cfg, "scale_mode", "raw")
            else:
                raise ConnectionError("All propar reads failed (ID 205 & ID 8).")

        self.flow_sensor = instr
        logger.info("FlowSensor: connected via propar library.")
        self._error_count = 0
        self._last_good_flow = 0.0

    def _connect_via_serial(self) -> None:
        logger.info("FlowSensor: using raw pyserial ProPar fallback.")
        ser = _ProParSerial(self.cfg.port, self.cfg.baudrate, self.cfg.address)

        # Probe candidates in priority order until one yields a cmd=0x02 DATA response.
        # PP_TYPE_FLOAT=0x20 per Bronkhorst FlowBus docs (4-byte IEEE 754 big-endian).
        # parm=6="Volume Flow", parm=5="Normal Flow", parm=0=config default.
        # Also probe both byte orders for (parm, type) since some sources differ.
        p = self.cfg.proc_nr  # typically 33
        n = self.cfg.parm_nr  # config default (may be wrong; will also try 6/5)
        candidates: list[Tuple[int, int, int]] = [
            (p,  0x20, 6),   # proc 33, PP_TYPE_FLOAT=0x20, parm=6 (Volume Flow)
            (p,  0x20, 5),   # proc 33, PP_TYPE_FLOAT=0x20, parm=5 (Normal Flow)
            (p,  0x20, n),   # proc 33, PP_TYPE_FLOAT=0x20, config parm
            (p,  0x05, 6),   # proc 33, type=0x05 (float alt), parm=6
            (p,  0x05, 5),   # proc 33, type=0x05 (float alt), parm=5
            (1,  0x02, 0),   # proc 1, uint16 Measure (0-32000 raw count)
        ]

        fmt = ser.probe(candidates)
        if fmt is None:
            logger.error(
                f"FlowSensor: no valid ProPar response on {self.cfg.port} "
                f"— tried all candidate formats"
            )
            ser.close()
            return

        self._serial_fmt = fmt
        self.flow_sensor = ser
        logger.info(
            f"FlowSensor: connected via raw pyserial ProPar "
            f"(proc={fmt[0]:#04x}, type={fmt[1]:#04x}, parm={fmt[2]})."
        )
        self._error_count = 0
        self._last_good_flow = 0.0

    def get_flow(self) -> float:
        if self.flow_sensor is None:
            return 0.0

        try:
            if isinstance(self.flow_sensor, _ProParSerial):
                if self._serial_fmt is None:
                    return 0.0
                proc, ptype, parm = self._serial_fmt
                data = self.flow_sensor.read(proc, ptype, parm)
                if data is None:
                    return self._last_good_flow
                if len(data) >= 4:
                    # 4-byte IEEE 754 float (engineering units, ml/min)
                    val = struct.unpack(">f", data[:4])[0]
                elif len(data) >= 2 and ptype == 0x02:
                    # 2-byte uint16 raw count (0-32000), convert to ml/min
                    raw_count = struct.unpack(">H", data[:2])[0]
                    val = (raw_count / self.cfg.full_scale_raw) * self.cfg.full_scale_ml_min
                else:
                    return self._last_good_flow
                self._error_count = 0
                self._last_good_flow = val
                return val

            # propar library path
            if self._cached_parameter_id == 0:
                return 0.0

            data = self.flow_sensor.readParameter(self._cached_parameter_id)
            if data is None:
                return self._last_good_flow

            raw_value = float(data)
            if self.cfg.scale_mode == "engineering":
                flow_ml_min = raw_value
            else:
                if abs(raw_value) > self.cfg.full_scale_raw * 1.5:
                    return self._last_good_flow
                flow_ml_min = (raw_value / self.cfg.full_scale_raw) * self.cfg.full_scale_ml_min

            self._error_count = 0
            self._last_good_flow = flow_ml_min
            return flow_ml_min

        except Exception as e:
            self._error_count += 1
            logger.warning(f"FlowSensor: read error -> {e} (failures: {self._error_count})")
            return self._last_good_flow

    def close(self) -> None:
        if self.flow_sensor is None:
            return
        if isinstance(self.flow_sensor, _ProParSerial):
            self.flow_sensor.close()
        logger.info("FlowSensor: disconnected.")
        self.flow_sensor = None
