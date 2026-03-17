from __future__ import annotations

import csv
import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

from src.utils.path_utils import ensure_dir, project_root, resolve_under

logger = logging.getLogger(__name__)


def ts_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _safe_json(x: Any) -> str:
    try:
        return json.dumps(x, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return json.dumps(str(x), ensure_ascii=False, separators=(",", ":"))

def _as_plain(obj: Any) -> Any:
    if obj is None:
        return None
    
    # 🚀 FIX: Wir stellen sicher, dass es eine Instanz ist und keine leere Klassen-Blaupause
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _as_plain(v) for k, v in asdict(obj).items()}
        
    if isinstance(obj, dict):
        return {str(k): _as_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_as_plain(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)

def _fmt_float(x: Any, *, digits: int = 6) -> str:
    if x is None:
        return ""
    try:
        v = float(x)
    except Exception:
        return ""
    if v != v or v in (float("inf"), float("-inf")):
        return ""
    return f"{v:.{int(digits)}f}"


def _make_run_id(prefix: str = "run") -> str:
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{prefix}"


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


TELEMETRY_FIELDS = [
    "schema_version",
    "run_id",
    "ts",
    "t_s",
    "step",
    "event",
    "flow",
    "p1_set",
    "p1_meas",
    "p2_set",
    "p2_meas",
    "volume_ml",
    "loss_ml",
    "valves",
    "manual_active",
    "pressure_json",
    "extra_json",
]

EVENT_FIELDS = [
    "schema_version",
    "run_id",
    "ts",
    "t_s",
    "type",
    "payload_json",
]


@dataclass(frozen=True)
class RunPaths:
    run_dir: Path
    telemetry_csv: Path
    events_csv: Path
    meta_yaml: Path


@dataclass
class TelemetryStoreConfig:
    root_dir: str = "logs/runs"
    run_id_prefix: str = "run"
    flush_every_n: int = 25
    flush_every_s: float = 1.0
    fsync_on_flush: bool = False
    schema_version: int = 1
    write_meta_immediately: bool = True


class RunTelemetryStore:
    def __init__(
        self,
        *,
        store_cfg: Optional[TelemetryStoreConfig] = None,
        run_id: Optional[str] = None,
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.cfg = store_cfg or TelemetryStoreConfig()
        self.run_id = str(run_id or _make_run_id(self.cfg.run_id_prefix))

        root = project_root(__file__)
        run_root = Path(ensure_dir(resolve_under(root, self.cfg.root_dir)))
        run_dir = Path(resolve_under(str(run_root), self.run_id))
        ensure_dir(str(run_dir))

        self.paths = RunPaths(
            run_dir=run_dir,
            telemetry_csv=run_dir / "telemetry.csv",
            events_csv=run_dir / "events.csv",
            meta_yaml=run_dir / "meta.yaml",
        )

        self._lock = threading.RLock()
        self._t0_monotonic: Optional[float] = None

        self._telemetry_fp = open(self.paths.telemetry_csv, "w", newline="", encoding="utf-8")
        self._events_fp = open(self.paths.events_csv, "w", newline="", encoding="utf-8")

        self._telemetry_writer = csv.DictWriter(self._telemetry_fp, fieldnames=list(TELEMETRY_FIELDS))
        self._events_writer = csv.DictWriter(self._events_fp, fieldnames=list(EVENT_FIELDS))

        self._telemetry_writer.writeheader()
        self._events_writer.writeheader()

        self._telemetry_count = 0
        self._events_count = 0
        self._last_flush_monotonic = time.monotonic()

        self._meta: Dict[str, Any] = {
            "created": ts_iso(),
            "schema_version": int(self.cfg.schema_version),
            "run_id": self.run_id,
            "paths": {
                "run_dir": str(self.paths.run_dir),
                "telemetry_csv": str(self.paths.telemetry_csv),
                "events_csv": str(self.paths.events_csv),
                "meta_yaml": str(self.paths.meta_yaml),
            },
            "env": {
                "computer": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "",
                "user": os.environ.get("USERNAME") or os.environ.get("USER") or "",
                "pid": os.getpid(),
            },
            "meta": _as_plain(dict(meta or {})),
        }

        if self.cfg.write_meta_immediately:
            self.write_meta()

        logger.info("RunTelemetryStore initialized: %s", str(self.paths.run_dir))

    def close(self) -> None:
        with self._lock:
            try:
                self._flush(force=True)
            except Exception:
                pass
            try:
                self._telemetry_fp.close()
            except Exception:
                pass
            try:
                self._events_fp.close()
            except Exception:
                pass

    def write_meta(self, extra: Optional[Mapping[str, Any]] = None) -> None:
        with self._lock:
            if extra:
                self._meta.setdefault("meta", {})
                if isinstance(self._meta["meta"], dict):
                    for k, v in dict(extra).items():
                        self._meta["meta"][str(k)] = _as_plain(v)
            payload = yaml.safe_dump(_as_plain(self._meta), sort_keys=False, allow_unicode=True)
            _atomic_write_text(self.paths.meta_yaml, payload)

    def set_run_start(self, t0_monotonic: Optional[float] = None) -> None:
        with self._lock:
            if self._t0_monotonic is None:
                self._t0_monotonic = float(t0_monotonic if t0_monotonic is not None else time.monotonic())

    def t_s(self) -> float:
        with self._lock:
            if self._t0_monotonic is None:
                self._t0_monotonic = time.monotonic()
            return float(time.monotonic() - self._t0_monotonic)

    def write_sample(self, sample: Mapping[str, Any]) -> None:
        with self._lock:
            if self._t0_monotonic is None:
                self._t0_monotonic = time.monotonic()

            t_val = sample.get("t", sample.get("time", None))
            if t_val is None:
                t_val = self.t_s()

            pressure_map = sample.get("pressure", None)

            known = {
                "t",
                "time",
                "step",
                "event",
                "flow",
                "p1_set",
                "p1_meas",
                "p2_set",
                "p2_meas",
                "volume_ml",
                "loss_ml",
                "valves",
                "valve_state",
                "manual_active",
                "pressure",
            }
            extra = {k: _as_plain(v) for k, v in dict(sample).items() if k not in known}

            valves = sample.get("valves", sample.get("valve_state", ""))

            row = {
                "schema_version": str(int(self.cfg.schema_version)),
                "run_id": str(self.run_id),
                "ts": ts_iso(),
                "t_s": _fmt_float(t_val),
                "step": str(sample.get("step", "")),
                "event": str(sample.get("event", "")),
                "flow": _fmt_float(sample.get("flow", None)),
                "p1_set": _fmt_float(sample.get("p1_set", None)),
                "p1_meas": _fmt_float(sample.get("p1_meas", None)),
                "p2_set": _fmt_float(sample.get("p2_set", None)),
                "p2_meas": _fmt_float(sample.get("p2_meas", None)),
                "volume_ml": _fmt_float(sample.get("volume_ml", None)),
                "loss_ml": _fmt_float(sample.get("loss_ml", None)),
                "valves": str(valves),
                "manual_active": "1" if bool(sample.get("manual_active", False)) else "0",
                "pressure_json": _safe_json(_as_plain(pressure_map)) if pressure_map is not None else "",
                "extra_json": _safe_json(extra) if extra else "",
            }

            self._telemetry_writer.writerow(row)
            self._telemetry_count += 1
            self._flush(force=False)

    def write_event(
        self,
        event_type: str,
        payload: Optional[Mapping[str, Any]] = None,
        *,
        t_s: Optional[float] = None,
    ) -> None:
        with self._lock:
            if self._t0_monotonic is None:
                self._t0_monotonic = time.monotonic()
            if t_s is None:
                t_s = self.t_s()

            row = {
                "schema_version": str(int(self.cfg.schema_version)),
                "run_id": str(self.run_id),
                "ts": ts_iso(),
                "t_s": _fmt_float(t_s),
                "type": str(event_type),
                "payload_json": _safe_json(_as_plain(payload or {})),
            }
            self._events_writer.writerow(row)
            self._events_count += 1
            self._flush(force=False)

    def _flush(self, *, force: bool = False) -> None:
        now = time.monotonic()
        n = max(1, int(self.cfg.flush_every_n))
        due_count = ((self._telemetry_count % n) == 0) or ((self._events_count % n) == 0)
        due_time = (now - float(self._last_flush_monotonic)) >= float(self.cfg.flush_every_s)

        if not force and not (due_count or due_time):
            return

        try:
            self._telemetry_fp.flush()
        except Exception:
            pass
        try:
            self._events_fp.flush()
        except Exception:
            pass

        if bool(self.cfg.fsync_on_flush):
            try:
                os.fsync(self._telemetry_fp.fileno())
            except Exception:
                pass
            try:
                os.fsync(self._events_fp.fileno())
            except Exception:
                pass

        self._last_flush_monotonic = now


def build_run_meta(
    *,
    experiment_config: Optional[Any] = None,
    run_params: Optional[Any] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    if experiment_config is not None:
        meta["experiment_config"] = _as_plain(experiment_config)
    if run_params is not None:
        meta["run_params"] = _as_plain(run_params)
    if extra:
        meta["extra"] = _as_plain(dict(extra))
    return meta