# src/gui/monitor/server.py
from __future__ import annotations

import json
import logging
import secrets
import socket
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# ---------------- Model ----------------

@dataclass
class MonitorState:
    ts_iso: str = ""
    step: str = "IDLE"
    status: str = "Idle"
    phase_label: str = ""
    manual_active: bool = False

    loss_ml: float = 0.0
    progress_pct: float = 0.0
    progress_text: str = ""
    flow: Optional[float] = None

    p1_set: Optional[float] = None
    p1_meas: Optional[float] = None
    p2_set: Optional[float] = None
    p2_meas: Optional[float] = None

    valves: str = "—"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def _guess_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return ip or "127.0.0.1"
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass

# ---------------- State store ----------------

class _StateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = MonitorState(ts_iso=_now_iso())

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._state, k):
                    setattr(self._state, k, v)
            self._state.ts_iso = _now_iso()

    def snapshot(self) -> MonitorState:
        with self._lock:
            return MonitorState(**asdict(self._state))

# ---------------- HTML (High-Tech Chroma) ----------------

_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<title>Chonker Telemetry</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root {
  --bg: #090B10;
  --card: #111520;
  --text: #F8FAFC;
  --muted: #94A3B8;
  --border: #1F2937;
  --cyan: #00E5FF;
  --green: #00E676;
  --red: #FF1744;
}
* { box-sizing: border-box; }
body {
  margin: 15px;
  background-color: var(--bg);
  color: var(--text);
  font-family: 'Consolas', 'Courier New', monospace;
}
.hdr {
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 2px solid var(--border);
  padding-bottom: 12px; margin-bottom: 20px;
}
.h1 { font-size: 20px; font-weight: 900; color: var(--text); letter-spacing: 2px; margin: 0; }
.auth-badge { font-size: 11px; color: #000; background: var(--green); padding: 4px 10px; border-radius: 4px; font-weight: bold;}
.grid-top {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px;
}
.kpi-box {
  background: var(--card); border: 1px solid var(--border); border-top: 3px solid var(--cyan);
  padding: 15px; border-radius: 6px;
}
.kpi-box:nth-child(2) { border-top-color: var(--green); }
.kpi-box:nth-child(3) { border-top-color: #A0AEC0; }
.kpi-box:nth-child(4) { border-top-color: var(--text); }

.kpi-title { font-size: 11px; color: var(--muted); font-weight: bold; margin-bottom: 8px; }
.kpi-val { font-size: 24px; font-weight: bold; color: var(--text); }
.val-cyan { color: var(--cyan); }
.val-green { color: var(--green); }

.chart-container {
  background: var(--card); border: 1px solid var(--border); padding: 15px; border-radius: 6px;
  position: relative; height: 35vh; width: 100%; margin-bottom: 20px;
}

.status-bar {
  display: flex; justify-content: space-between; align-items: center;
  background: var(--card); border: 1px solid var(--border); padding: 15px; border-radius: 6px;
  font-size: 12px; font-weight: bold; color: var(--muted);
}
.status-bar span { color: var(--text); font-size: 14px; margin-left: 5px; }
.status-bar span.active { color: var(--cyan); }
.status-bar span.error { color: var(--red); }
</style>
</head>
<body>

  <div class="hdr">
    <div class="h1">SYS_TELEMETRY // CHONKER</div>
    <div class="auth-badge">AUTH OK</div>
  </div>

  <!-- PHASE PROGRESS -->
  <div id="phase-bar" class="status-bar" style="margin-bottom:15px; flex-direction:column; align-items:stretch; gap:8px; display:none;">
    <div style="display:flex; justify-content:space-between; align-items:center;">
      <span id="phase_label" style="color:var(--cyan); font-size:14px; font-weight:bold;">—</span>
      <span id="progress_text" style="color:var(--muted); font-size:12px;">—</span>
    </div>
    <div style="background:#0F172A; border-radius:4px; height:8px; overflow:hidden;">
      <div id="progress_fill" style="height:100%; width:0%; background:var(--cyan); border-radius:4px; transition:width 0.3s;"></div>
    </div>
  </div>

  <div class="grid-top">
    <div class="kpi-box">
      <div class="kpi-title">P1 Main (mbar)</div>
      <div class="kpi-val val-cyan" id="p1_meas">—</div>
      <div class="kpi-sub" id="p1_set" style="color:var(--muted); font-size:11px; margin-top:2px;">SET: —</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-title">P2 Backwash (mbar)</div>
      <div class="kpi-val val-green" id="p2_meas">—</div>
      <div class="kpi-sub" id="p2_set" style="color:var(--muted); font-size:11px; margin-top:2px;">SET: —</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-title">Flow Rate</div>
      <div class="kpi-val" id="flow">—</div>
    </div>
    <div class="kpi-box">
      <div class="kpi-title">Valve State</div>
      <div class="kpi-val" id="valves" style="font-size: 16px;">—</div>
    </div>
  </div>

  <div class="chart-container">
    <canvas id="liveChart"></canvas>
  </div>

  <div class="status-bar">
    <div>STEP:<span id="step" class="active">—</span></div>
    <div>SYS:<span id="status">—</span></div>
    <div>LOSS:<span id="loss">—</span></div>
  </div>

<script>
const qs = new URLSearchParams(location.search);
const token = qs.get("token") || "";

const ctx = document.getElementById('liveChart').getContext('2d');
Chart.defaults.color = '#64748B';
Chart.defaults.font.family = "'Consolas', monospace";

const maxDataPoints = 60;
const chart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label: 'P1 Main', borderColor: '#00E5FF', backgroundColor: 'rgba(0, 229, 255, 0.1)', borderWidth: 2, pointRadius: 0, data: [], fill: true, tension: 0.3 },
            { label: 'P2 Backwash', borderColor: '#00E676', backgroundColor: 'transparent', borderWidth: 2, borderDash: [5, 5], pointRadius: 0, data: [], tension: 0.3 },
            { label: 'Flow', borderColor: '#EC4899', backgroundColor: 'rgba(236, 72, 153, 0.08)', borderWidth: 1.5, pointRadius: 0, data: [], fill: true, tension: 0.3, yAxisID: 'y1' }
        ]
    },
    options: {
        responsive: true, maintainAspectRatio: false,
        animation: false,
        interaction: { intersect: false },
        scales: {
            x: { display: false },
            y: { grid: { color: '#1F2937' }, beginAtZero: true, position: 'left', title: { display: true, text: 'mbar', color: '#64748B' } },
            y1: { grid: { drawOnChartArea: false }, beginAtZero: true, position: 'right', title: { display: true, text: 'mL/min', color: '#64748B' } }
        },
        plugins: { legend: { position: 'top', labels: { boxWidth: 15, font: {weight: 'bold'} } } }
    }
});

let timeIndex = 0;

const phaseColors = {
    'FILLING': '#00E5FF', 'PHASE_A': '#8B5CF6', 'PHASE_B': '#F59E0B',
    'PHASE_C': '#EC4899', 'FINISHED': '#00E676', 'ABORTED': '#FF1744'
};

async function tick() {
  if(!token) return;
  try {
    const r = await fetch("/status?token=" + encodeURIComponent(token), {cache:"no-store"});
    if(!r.ok) return;
    const s = await r.json();

    document.getElementById("p1_meas").textContent = s.p1_meas != null ? Math.round(s.p1_meas) : "—";
    document.getElementById("p2_meas").textContent = s.p2_meas != null ? Math.round(s.p2_meas) : "—";
    document.getElementById("p1_set").textContent = s.p1_set != null ? "SET: " + Math.round(s.p1_set) + " mbar" : "SET: —";
    document.getElementById("p2_set").textContent = s.p2_set != null ? "SET: " + Math.round(s.p2_set) + " mbar" : "SET: —";
    document.getElementById("flow").textContent = s.flow != null ? s.flow.toFixed(3) : "—";
    document.getElementById("valves").textContent = s.valves ?? "—";

    document.getElementById("step").textContent = s.step ?? "—";
    document.getElementById("loss").textContent = (s.loss_ml ?? 0).toFixed(3) + " mL";

    // Phase Progress Bar
    const phaseBar = document.getElementById("phase-bar");
    if (s.phase_label && s.step !== "IDLE") {
        phaseBar.style.display = "flex";
        const pLabel = document.getElementById("phase_label");
        pLabel.textContent = s.phase_label;
        let pColor = phaseColors[s.step] || '#00E5FF';
        for (const [k, c] of Object.entries(phaseColors)) { if (s.step.includes(k)) { pColor = c; break; } }
        pLabel.style.color = pColor;
        document.getElementById("progress_text").textContent = s.progress_text || "";
        const fill = document.getElementById("progress_fill");
        fill.style.width = Math.min(100, Math.max(0, s.progress_pct || 0)) + "%";
        fill.style.background = pColor;
    } else {
        phaseBar.style.display = "none";
    }

    // Soll/Ist Drift-Indikator P1
    if (s.p1_set != null && s.p1_meas != null && s.p1_set > 10) {
        const drift = Math.abs(s.p1_meas - s.p1_set) / s.p1_set * 100;
        document.getElementById("p1_set").style.color = drift > 10 ? '#FF1744' : 'var(--muted)';
    }

    const stEl = document.getElementById("status");
    stEl.textContent = s.status ?? "—";
    const statusText = (s.status || "").toLowerCase();
    if(statusText.includes("fail") || statusText.includes("error") || statusText.includes("alarm")) {
        stEl.className = "error";
    } else if(statusText.includes("wait") || statusText.includes("confirm")) {
        stEl.className = ""; stEl.style.color = "#F59E0B";
    } else {
        stEl.className = "active"; stEl.style.color = "";
    }

    // Chart: P1, P2, und Flow
    const p1_val = s.p1_meas != null ? s.p1_meas : null;
    const p2_val = s.p2_meas != null ? s.p2_meas : null;
    const f_val = s.flow != null ? s.flow : null;

    if (p1_val !== null || p2_val !== null || f_val !== null) {
        chart.data.labels.push(timeIndex++);
        chart.data.datasets[0].data.push(p1_val || 0);
        chart.data.datasets[1].data.push(p2_val || 0);
        chart.data.datasets[2].data.push(f_val || 0);

        if (chart.data.labels.length > maxDataPoints) {
            chart.data.labels.shift();
            chart.data.datasets.forEach(ds => ds.data.shift());
        }
        chart.update();
    }

  } catch(e) {}
}

setInterval(tick, 500);
tick();
</script>
</body>
</html>
"""

class MonitorServer:
    def __init__(self, *, host: str = "0.0.0.0", port: int = 8765) -> None:
        self.host = str(host)
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
            server_version = "LittleChonkerMonitor/2.0"

            def _auth_ok(self) -> bool:
                q = parse_qs(urlparse(self.path).query)
                qtok = q.get("token", [""])[0]
                htok = self.headers.get("X-Auth-Token", "") or ""
                auth = self.headers.get("Authorization", "") or ""
                bearer = ""
                if auth.startswith("Bearer "):
                    bearer = auth[len("Bearer "):].strip()
                return (qtok == token) or (htok == token) or (bearer == token)

            def _send(
                    self,
                    code: int,
                    body: bytes,
                    content_type: str,
                    *,
                    extra_headers: Optional[Dict[str, str]] = None,
            ) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Referrer-Policy", "no-referrer")
                if extra_headers:
                    for k, v in extra_headers.items():
                        self.send_header(k, v)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    return

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, X-Auth-Token, Content-Type")
                self.send_header("Access-Control-Max-Age", "600")
                self.end_headers()

            def do_GET(self) -> None:
                u = urlparse(self.path)
                if u.path == "/health":
                    return self._send(200, b"ok", "text/plain; charset=utf-8")
                if u.path == "/info":
                    payload = {
                        "server": "LittleChonkerMonitor",
                        "version": "2.0",
                        "token_present": bool(token),
                        "note": "Use /status?token=... for JSON status.",
                    }
                    b = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    return self._send(200, b, "application/json; charset=utf-8")
                if u.path in ("/", "/index.html"):
                    return self._send(200, _HTML.encode("utf-8"), "text/html; charset=utf-8")
                if u.path == "/status":
                    if not self._auth_ok():
                        return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
                    snap = store.snapshot()
                    b = snap.to_json().encode("utf-8")
                    return self._send(
                        200,
                        b,
                        "application/json; charset=utf-8",
                        extra_headers={"Access-Control-Allow-Origin": "*"},
                    )
                return self._send(404, b"Not Found", "text/plain; charset=utf-8")

            def log_message(self, _format: str, *args: Any) -> None:
                return

        httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        httpd.daemon_threads = True
        self._httpd = httpd

        try:
            self.port = int(httpd.server_address[1])
        except Exception:
            pass

        t = threading.Thread(target=httpd.serve_forever, daemon=True, name="MonitorServer")
        self._thread = t
        t.start()
        logger.info("MonitorServer started (bind=%s:%s, lan=%s, url=%s)", self.host, self.port, self.lan_ip, self.url())

    def stop(self) -> None:
        httpd = self._httpd
        th = self._thread
        if httpd is None:
            return
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            logger.exception("MonitorServer stop failed")
        finally:
            self._httpd = None
            self._thread = None
        try:
            if th is not None and th.is_alive():
                th.join(timeout=1.5)
        except Exception:
            pass
        logger.info("MonitorServer stopped")

    def base_url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/"

    def url(self) -> str:
        return f"http://{self.lan_ip}:{self.port}/?token={self.token}"

    def token_short(self) -> str:
        return self.token[:10]

    def update_step(self, step: str) -> None:
        s = str(step)
        phase_labels = {
            "FILLING": "PHASE 0: FILLING",
            "PHASE_A": "PHASE A: RAMP UP",
            "PHASE_B": "PHASE B: STEADY STATE",
            "PHASE_C": "PHASE C: RAMP DOWN",
            "FINISHED": "COMPLETE",
            "ABORTED": "ABORTED",
        }
        label = s
        for key, lbl in phase_labels.items():
            if key in s:
                label = lbl
                break
        self._store.update(step=s, phase_label=label)

    def update_status(self, status: str) -> None:
        self._store.update(status=str(status))

    def update_manual_active(self, active: bool) -> None:
        self._store.update(manual_active=bool(active))

    def update_loss(self, loss_ml: float) -> None:
        self._store.update(loss_ml=float(loss_ml))

    def update_progress(self, pct: float, text: str = "") -> None:
        self._store.update(progress_pct=float(pct), progress_text=str(text))

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
        payload: Dict[str, Any] = {}
        if flow is not None: payload["flow"] = float(flow)
        if p1_set is not None: payload["p1_set"] = float(p1_set)
        if p1_meas is not None: payload["p1_meas"] = float(p1_meas)
        if p2_set is not None: payload["p2_set"] = float(p2_set)
        if p2_meas is not None: payload["p2_meas"] = float(p2_meas)
        if valves is not None: payload["valves"] = str(valves)
        if payload:
            self._store.update(**payload)