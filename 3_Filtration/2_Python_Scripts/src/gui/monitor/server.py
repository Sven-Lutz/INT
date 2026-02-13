from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from dataclasses import dataclass, asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse


@dataclass
class MonitorState:
    ts_iso: str = ""
    step: str = "IDLE"
    status: str = "Idle"
    loss_ml: float = 0.0
    flow: Optional[float] = None
    p1_set: Optional[float] = None
    p1_meas: Optional[float] = None
    p2_set: Optional[float] = None
    p2_meas: Optional[float] = None
    valves: str = "—"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _guess_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass


class _StateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = MonitorState(ts_iso=_now_iso())

    def update(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self.state, k):
                    setattr(self.state, k, v)
            self.state.ts_iso = _now_iso()

    def snapshot(self) -> MonitorState:
        with self._lock:
            return MonitorState(**asdict(self.state))


class MonitorServer:
    def __init__(self, *, host: str = "0.0.0.0", port: int = 8765) -> None:
        self.host = host
        self.port = int(port)
        self.token = secrets.token_urlsafe(16)
        self._store = _StateStore()

        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        self.lan_ip = _guess_lan_ip()

    def start(self) -> None:
        if self._httpd is not None:
            return

        store = self._store
        token = self.token

        class Handler(BaseHTTPRequestHandler):
            def _auth_ok(self) -> bool:
                q = parse_qs(urlparse(self.path).query)
                return q.get("token", [""])[0] == token

            def _send(self, code: int, body: bytes, content_type: str) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                u = urlparse(self.path)
                if u.path in ("/", "/index.html"):
                    if not self._auth_ok():
                        return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
                    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Little Chonker Monitor</title>
<style>
body{{font-family:system-ui,Segoe UI,Arial; margin:16px;}}
.card{{border:1px solid #ddd; border-radius:14px; padding:14px; margin:10px 0;}}
.h1{{font-size:22px; font-weight:700; margin:0 0 8px 0;}}
.kv{{display:grid; grid-template-columns:160px 1fr; gap:6px 12px;}}
.mono{{font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;}}
.badge{{display:inline-block; padding:4px 10px; border-radius:999px; background:#eee;}}
.ok{{background:#fff3cd; border:1px solid #ffeeba;}}
</style>
</head>
<body>
<div class="card">
  <div class="h1">Little Chonker Monitor</div>
  <div class="mono">token: {token}</div>
</div>

<div class="card">
  <div class="kv">
    <div>Timestamp</div><div class="mono" id="ts">—</div>
    <div>Step</div><div><span class="badge" id="step">—</span></div>
    <div>Status</div><div id="status">—</div>
  </div>
</div>

<div class="card">
  <div class="kv mono">
    <div>Loss</div><div id="loss">—</div>
    <div>Flow</div><div id="flow">—</div>
    <div>P1 (set/meas)</div><div id="p1">—</div>
    <div>P2 (set/meas)</div><div id="p2">—</div>
    <div>Valves</div><div id="valves">—</div>
  </div>
</div>

<script>
const token = new URLSearchParams(location.search).get("token");
async function tick(){{
  const r = await fetch("/status?token=" + encodeURIComponent(token), {{cache:"no-store"}});
  if(!r.ok) return;
  const s = await r.json();
  document.getElementById("ts").textContent = s.ts_iso ?? "—";
  document.getElementById("step").textContent = s.step ?? "—";
  document.getElementById("status").textContent = s.status ?? "—";
  document.getElementById("loss").textContent = (s.loss_ml ?? 0).toFixed(3) + " mL";
  document.getElementById("flow").textContent = (s.flow==null) ? "—" : String(s.flow);
  const p1 = (s.p1_set==null && s.p1_meas==null) ? "—" : `${{s.p1_set ?? "—"}} / ${{s.p1_meas ?? "—"}}`;
  const p2 = (s.p2_set==null && s.p2_meas==null) ? "—" : `${{s.p2_set ?? "—"}} / ${{s.p2_meas ?? "—"}}`;
  document.getElementById("p1").textContent = p1;
  document.getElementById("p2").textContent = p2;
  document.getElementById("valves").textContent = s.valves ?? "—";
}}
setInterval(tick, 500);
tick();
</script>
</body>
</html>
"""
                    return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

                if u.path == "/status":
                    if not self._auth_ok():
                        return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
                    snap = store.snapshot()
                    return self._send(200, snap.to_json().encode("utf-8"), "application/json; charset=utf-8")

                return self._send(404, b"Not Found", "text/plain; charset=utf-8")

            def log_message(self, format, *args) -> None:
                return

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is None:
            return
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        finally:
            self._httpd = None
            self._thread = None

    def url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/?token={self.token}"

    def update_step(self, step: str) -> None:
        self._store.update(step=step)

    def update_status(self, status: str) -> None:
        self._store.update(status=status)

    def update_loss(self, loss_ml: float) -> None:
        self._store.update(loss_ml=float(loss_ml))

    def update_metrics(
        self,
        *,
        flow: Optional[float] = None,
        p1_set: Optional[float] = None,
        p1_meas: Optional[float] = None,
        p2_set: Optional[float] = None,
        p2_meas: Optional[float] = None,
        valves: Optional[str] = None,
    ) -> None:
        payload = {}
        if flow is not None:
            payload["flow"] = float(flow)
        if p1_set is not None:
            payload["p1_set"] = float(p1_set)
        if p1_meas is not None:
            payload["p1_meas"] = float(p1_meas)
        if p2_set is not None:
            payload["p2_set"] = float(p2_set)
        if p2_meas is not None:
            payload["p2_meas"] = float(p2_meas)
        if valves is not None:
            payload["valves"] = str(valves)
        if payload:
            self._store.update(**payload)
