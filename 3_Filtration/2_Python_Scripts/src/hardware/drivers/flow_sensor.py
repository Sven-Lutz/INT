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
    Bronkhorst ProPar ASCII protocol over raw pyserial.

    Frame format matches the bronkhorst-propar 1.3 library (ASCII mode):

      TX: :{(len(data)+1):02X}{addr:02X}04{proc:02X}{pb:02X}{proc:02X}{pb:02X}\\r\\n
      RX: :{(len(data)+1):02X}{node:02X}02{proc:02X}{pb:02X}{value_bytes}\\r\\n

    Where pb = (parm_nr & 0x1F) | wire_type_bits:
      wire_type 0x40 = INT32 on wire (= PP_TYPE_FLOAT, 4 bytes, big-endian IEEE 754)
      wire_type 0x20 = INT16 on wire (= PP_TYPE_INT16, 2 bytes, big-endian uint16)

    Length byte in frame = len(data_bytes_excl_node) + 1.

    cmd=0x02 = DATA response (wanted)
    cmd=0x04 = RS-485 half-duplex echo of own request (skip)
    cmd=0x00 = STATUS/ERROR response — data[1] is Bronkhorst status code
               (e.g. 34=PP_STATUS_PROTOCOL_ERROR, 4=PP_STATUS_PARM_NUMBER)
    """

    # Wire type bits ORed into the parm byte
    WIRE_TYPE_FLOAT = 0x40   # INT32 on wire, reinterpreted as IEEE 754 float
    WIRE_TYPE_INT16 = 0x20   # unsigned 16-bit integer (0-32000 raw count)

    def __init__(self, port: str, baudrate: int, address: int, timeout: float = 1.5):
        self._ser = serial.Serial(
            port, baudrate=baudrate, timeout=timeout,
            bytesize=8, parity="N", stopbits=1,
        )
        self._addr = address & 0xFF
        self._lock = threading.Lock()

    def _query(self, proc: int, parm: int, wire_type: int) -> Optional[bytes]:
        """Send one ProPar read request; return value bytes from the cmd=0x02 answer."""
        with self._lock:
            pb = (parm & 0x1F) | (wire_type & 0x60)
            # data = [cmd, proc_index, parm_byte, proc_nr, parm_byte]  (5 bytes)
            data = bytes([0x04, proc & 0xFF, pb, proc & 0xFF, pb])
            # length byte in frame = len(data) + 1  (bronkhorst-propar convention)
            frame = f":{(len(data) + 1):02X}{self._addr:02X}" + data.hex().upper() + "\r\n"
            logger.debug(f"ProPar TX: {frame.strip()!r}")
            self._ser.reset_input_buffer()
            self._ser.write(frame.encode("ascii"))

            for attempt in range(4):
                resp = self._ser.readline()
                logger.debug(f"ProPar RX[{attempt}]: {resp!r}")
                if not resp or resp[0:1] != b":":
                    continue
                hex_body = resp[1:].decode("ascii", errors="ignore").strip()
                try:
                    raw = bytes.fromhex(hex_body)
                except ValueError:
                    logger.debug(f"ProPar RX[{attempt}]: hex decode failed on {hex_body!r}")
                    continue
                if len(raw) < 3:
                    continue

                cmd = raw[2]
                if cmd == 0x02 and len(raw) >= 5:
                    # raw = [len_byte, node, 0x02, proc_nr, parm_byte, value_bytes...]
                    return raw[5:]
                if cmd == 0x04:
                    continue  # RS-485 echo of own TX, keep reading
                if cmd == 0x00:
                    err = raw[3] if len(raw) > 3 else 0xFF
                    logger.debug(
                        f"ProPar: STATUS/ERROR (code={err}) for "
                        f"proc={proc:#04x} parm={parm} wire_type={wire_type:#04x}"
                    )
                    return None

        return None

    def probe(self, candidates: list[Tuple[int, int, int]]) -> Optional[Tuple[int, int, int]]:
        """Try each (proc, parm, wire_type) candidate; return first that gets a DATA response."""
        for proc, parm, wire_type in candidates:
            logger.info(
                f"ProPar probe: trying proc={proc:#04x} parm={parm} wire_type={wire_type:#04x}"
            )
            data = self._query(proc, parm, wire_type)
            if data is not None:
                logger.info(
                    f"ProPar probe: SUCCESS proc={proc:#04x} parm={parm} "
                    f"wire_type={wire_type:#04x} — data={data.hex()}"
                )
                return (proc, parm, wire_type)
        return None

    def read(self, proc: int, parm: int, wire_type: int) -> Optional[bytes]:
        """Return raw value bytes using a confirmed (proc, parm, wire_type)."""
        return self._query(proc, parm, wire_type)

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
        self._serial_fmt: Optional[Tuple[int, int, int]] = None  # pyserial path: (proc, parm, wire_type)
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

        # Probe candidates: (proc_nr, parm_nr, wire_type)
        # wire_type 0x40 = FLOAT (INT32 on wire, 4 bytes, big-endian IEEE 754)
        # wire_type 0x20 = INT16 (2 bytes, big-endian uint16, 0-32000 raw count)
        # parm=6 = "Volume Flow" (ml/min float), parm=5 = "Normal Flow"
        # proc=1, parm=0, INT16 = classic integer Measure (0-32000 raw)
        p = self.cfg.proc_nr  # typically 33
        n = self.cfg.parm_nr  # from config (default 6 = Volume Flow)
        F = _ProParSerial.WIRE_TYPE_FLOAT
        I = _ProParSerial.WIRE_TYPE_INT16
        candidates: list[Tuple[int, int, int]] = [
            (p, 6, F),   # proc 33, parm 6 = Volume Flow, float
            (p, 5, F),   # proc 33, parm 5 = Normal Flow, float
            (p, n, F),   # proc 33, config parm, float
            (1, 0, I),   # proc 1, parm 0 = Measure, uint16 (0-32000)
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
            f"(proc={fmt[0]:#04x}, parm={fmt[1]}, wire_type={fmt[2]:#04x})."
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
                proc, parm, wire_type = self._serial_fmt
                data = self.flow_sensor.read(proc, parm, wire_type)
                if data is None:
                    return self._last_good_flow
                if wire_type == _ProParSerial.WIRE_TYPE_FLOAT and len(data) >= 4:
                    # 4-byte big-endian IEEE 754 float (engineering units, ml/min)
                    val = struct.unpack(">f", data[:4])[0]
                elif wire_type == _ProParSerial.WIRE_TYPE_INT16 and len(data) >= 2:
                    # 2-byte uint16 raw count (0-32000), scale to ml/min
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
