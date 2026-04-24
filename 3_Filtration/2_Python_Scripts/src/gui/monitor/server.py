# src/gui/monitor/server.py
from __future__ import annotations

import json
import logging
import secrets
import socket
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
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
    volume_ml: float = 0.0
    run_elapsed_s: float = 0.0
    progress_pct: float = 0.0
    progress_text: str = ""
    flow: Optional[float] = None

    p1_set: Optional[float] = None
    p1_meas: Optional[float] = None
    p2_set: Optional[float] = None
    p2_meas: Optional[float] = None

    valves: str = "—"

    b1_current_ml: float = 0.0
    b1_target_ml: float = 0.0

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
    _HISTORY_MAXLEN = 3600  # ~10 min at 200ms sample rate

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = MonitorState(ts_iso=_now_iso())
        self._history: deque = deque(maxlen=self._HISTORY_MAXLEN)

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self._state, k):
                    setattr(self._state, k, v)
            self._state.ts_iso = _now_iso()

    def snapshot(self) -> MonitorState:
        with self._lock:
            return MonitorState(**asdict(self._state))

    def write_sample(self, d: dict) -> None:
        """Appends a compact telemetry point to the history ring buffer."""
        with self._lock:
            self._history.append({
                "t": d.get("t", d.get("run_elapsed_s", 0.0)),
                "p1": d.get("p1_meas", None),
                "p1s": d.get("p1_set", None),
                "p2": d.get("p2_meas", None),
                "fl": d.get("flow", None),
                "vol": d.get("volume_ml", None),
                "loss": d.get("loss_ml", None),
                "step": d.get("step", "IDLE"),
            })

    def get_history(self) -> List[dict]:
        with self._lock:
            return list(self._history)

# ---------------- HTML Dashboard ----------------

_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/>
<title>Chonker Telemetry</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {
  --bg: #090B10;
  --card: #111520;
  --text: #F8FAFC;
  --muted: #64748B;
  --border: #1F2937;
  --cyan: #00E5FF;
  --green: #10B981;
  --pink: #EC4899;
  --amber: #F59E0B;
  --violet: #8B5CF6;
  --red: #FF1744;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: var(--bg); color: var(--text); font-family: 'Consolas', 'Courier New', monospace; }
body { padding: 12px; overflow-x: hidden; }

/* HEADER */
.hdr {
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 14px;
}
.hdr-title { font-size: 16px; font-weight: 900; letter-spacing: 2px; color: var(--text); }
.hdr-title span { color: var(--cyan); }
.hdr-right { display: flex; align-items: center; gap: 10px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); transition: background 0.3s; flex-shrink: 0; }
.dot.live { background: var(--green); box-shadow: 0 0 6px var(--green); }
.dot.dead { background: var(--red); }
.ts-label { font-size: 10px; color: var(--muted); }

/* FILLING BANNER */
.filling-banner {
  display: none; border: 2px solid var(--cyan); background: #0a2030;
  border-radius: 6px; padding: 12px 16px; margin-bottom: 14px;
  animation: pulse-border 1.4s ease-in-out infinite;
}
@keyframes pulse-border {
  0%, 100% { border-color: var(--cyan); }
  50% { border-color: rgba(0, 229, 255, 0.3); }
}
.filling-banner.show { display: block; }
.filling-banner-title { color: var(--cyan); font-size: 14px; font-weight: bold; margin-bottom: 4px; }
.filling-banner-sub { color: var(--muted); font-size: 12px; }

/* PHASE TIMELINE */
.phase-timeline {
  display: flex; gap: 4px; margin-bottom: 14px;
  background: var(--card); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 12px; overflow-x: auto;
}
.phase-step {
  flex: 1; min-width: 44px; text-align: center; padding: 5px 4px;
  font-size: 10px; font-weight: bold; border-radius: 4px; color: var(--muted);
  border: 1px solid transparent; transition: all 0.3s; letter-spacing: 0.5px;
  white-space: nowrap;
}
.phase-step.active { color: var(--text); border-color: currentColor; }

/* KPI GRID */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px; margin-bottom: 14px;
}
@media (min-width: 480px) { .kpi-grid { grid-template-columns: repeat(3, 1fr); } }
@media (min-width: 800px) { .kpi-grid { grid-template-columns: repeat(6, 1fr); } }

.kpi {
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px 10px; position: relative; overflow: hidden;
}
.kpi::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: var(--accent, var(--cyan));
}
.kpi-title { font-size: 9px; color: var(--muted); font-weight: bold; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; }
.kpi-val { font-size: 22px; font-weight: bold; color: var(--accent, var(--cyan)); line-height: 1; }
.kpi-sub { font-size: 10px; color: var(--muted); margin-top: 4px; }

/* CHART */
.chart-wrap {
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px; margin-bottom: 14px;
}
.chart-title { font-size: 10px; color: var(--muted); font-weight: bold; letter-spacing: 1px; margin-bottom: 8px; }
.chart-container { position: relative; height: 38vh; }

/* PROGRESS BAR */
.prog-wrap {
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 12px; margin-bottom: 14px; display: none;
}
.prog-wrap.show { display: block; }
.prog-header { display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 11px; font-weight: bold; }
.prog-bar-bg { background: #0F172A; border-radius: 4px; height: 8px; overflow: hidden; }
.prog-bar-fill { height: 100%; width: 0%; border-radius: 4px; transition: width 0.4s; background: var(--cyan); }

/* FOOTER STATUS */
.status-row {
  display: flex; gap: 8px; flex-wrap: wrap;
  background: var(--card); border: 1px solid var(--border); border-radius: 6px;
  padding: 10px 12px;
}
.status-item { font-size: 11px; color: var(--muted); }
.status-item b { color: var(--text); }
.status-item b.err { color: var(--red); }
.status-item b.warn { color: var(--amber); }
.status-item b.ok { color: var(--green); }
</style>
</head>
<body>

<!-- HEADER -->
<div class="hdr">
  <div class="hdr-title">CHONKER <span>//</span> TELEMETRY</div>
  <div class="hdr-right">
    <div class="ts-label" id="ts_label">—</div>
    <div class="dot" id="conn_dot" title="Connection status"></div>
  </div>
</div>

<!-- FILLING BANNER -->
<div class="filling-banner" id="filling_banner">
  <div class="filling-banner-title">⚠ MANUAL FILLING REQUIRED</div>
  <div class="filling-banner-sub">Waiting for operator confirmation at control station…</div>
</div>

<!-- PHASE TIMELINE -->
<div class="phase-timeline" id="phase_timeline" style="display:none;">
  <div class="phase-step" id="ps_bw"   data-step="BACKWASH">BACKWASH</div>
  <div class="phase-step" id="ps_fill" data-step="FILLING">FILL</div>
  <div class="phase-step" id="ps_a"    data-step="PHASE_A">RAMP A</div>
  <div class="phase-step" id="ps_b1"   data-step="PHASE_B1">HOLD B1</div>
  <div class="phase-step" id="ps_b2"   data-step="PHASE_B2">HOLD B2</div>
  <div class="phase-step" id="ps_c"    data-step="PHASE_C">RAMP C</div>
  <div class="phase-step" id="ps_done" data-step="FINISHED">DONE</div>
</div>

<!-- KPI GRID -->
<div class="kpi-grid">
  <div class="kpi" style="--accent: var(--cyan);">
    <div class="kpi-title">P1 Main</div>
    <div class="kpi-val" id="kpi_p1">—</div>
    <div class="kpi-sub" id="kpi_p1s">SET: —</div>
  </div>
  <div class="kpi" style="--accent: var(--green);">
    <div class="kpi-title">P2 Backwash</div>
    <div class="kpi-val" id="kpi_p2">—</div>
    <div class="kpi-sub" id="kpi_p2s">SET: —</div>
  </div>
  <div class="kpi" style="--accent: var(--pink);">
    <div class="kpi-title">Flow Rate</div>
    <div class="kpi-val" id="kpi_flow">—</div>
    <div class="kpi-sub">mL/min</div>
  </div>
  <div class="kpi" style="--accent: var(--amber);">
    <div class="kpi-title">Volume</div>
    <div class="kpi-val" id="kpi_vol">—</div>
    <div class="kpi-sub">mL</div>
  </div>
  <div class="kpi" style="--accent: var(--violet);">
    <div class="kpi-title">Loss / Target</div>
    <div class="kpi-val" id="kpi_loss">—</div>
    <div class="kpi-sub" id="kpi_prog_text">—</div>
  </div>
  <div class="kpi" style="--accent: var(--muted);">
    <div class="kpi-title">Runtime</div>
    <div class="kpi-val" id="kpi_rt" style="font-size:18px;">—</div>
    <div class="kpi-sub" id="kpi_step">IDLE</div>
  </div>
</div>

<!-- PROGRESS BAR -->
<div class="prog-wrap" id="prog_wrap">
  <div class="prog-header">
    <span id="prog_phase" style="color: var(--cyan);">—</span>
    <span id="prog_text" style="color: var(--muted);">—</span>
  </div>
  <div class="prog-bar-bg">
    <div class="prog-bar-fill" id="prog_fill"></div>
  </div>
</div>

<!-- CHART -->
<div class="chart-wrap">
  <div class="chart-title">LIVE TELEMETRY — FULL RUN HISTORY</div>
  <div class="chart-container">
    <canvas id="liveChart"></canvas>
  </div>
</div>

<!-- STATUS FOOTER -->
<div class="status-row">
  <div class="status-item">STEP: <b id="s_step">—</b></div>
  <div class="status-item">SYS: <b id="s_status">—</b></div>
  <div class="status-item">VALVES: <b id="s_valves">—</b></div>
  <div class="status-item">LOSS: <b id="s_loss">—</b></div>
</div>

<script>
// Token: read from URL once, persist in sessionStorage, then strip from URL.
// This prevents the token appearing in browser history or referer headers.
(function() {
  const qs = new URLSearchParams(location.search);
  const t = qs.get("token");
  if (t) {
    sessionStorage.setItem("chonker_token", t);
    qs.delete("token");
    const clean = location.pathname + (qs.toString() ? "?" + qs.toString() : "");
    history.replaceState(null, "", clean);
  }
})();
const TOKEN = sessionStorage.getItem("chonker_token") || "";

// ── Chart.js setup ──────────────────────────────────────────────
Chart.defaults.color = '#64748B';
Chart.defaults.font.family = "'Consolas', monospace";

const ctx = document.getElementById('liveChart').getContext('2d');
const chart = new Chart(ctx, {
  type: 'line',
  data: {
    datasets: [
      { label: 'P1 Meas',   borderColor: '#00E5FF', backgroundColor: 'rgba(0,229,255,0.06)', borderWidth: 2, pointRadius: 0, data: [], fill: true, tension: 0.2, yAxisID: 'yP' },
      { label: 'P1 Set',    borderColor: '#00E5FF', backgroundColor: 'transparent', borderWidth: 1, borderDash: [4,4], pointRadius: 0, data: [], tension: 0.2, yAxisID: 'yP' },
      { label: 'P2 Meas',   borderColor: '#10B981', backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, data: [], tension: 0.2, yAxisID: 'yP' },
      { label: 'Flow',      borderColor: '#EC4899', backgroundColor: 'rgba(236,72,153,0.07)', borderWidth: 1.5, pointRadius: 0, data: [], fill: true, tension: 0.3, yAxisID: 'yF' },
      { label: 'Volume',    borderColor: '#F59E0B', backgroundColor: 'transparent', borderWidth: 1.5, pointRadius: 0, data: [], tension: 0.2, yAxisID: 'yV', borderDash: [2,2] },
      { label: 'Loss',      borderColor: '#8B5CF6', backgroundColor: 'rgba(139,92,246,0.07)', borderWidth: 1.5, pointRadius: 0, data: [], fill: true, tension: 0.2, yAxisID: 'yV' },
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { intersect: false, mode: 'index' },
    parsing: { xAxisKey: 't', yAxisKey: 'v' },
    scales: {
      x: { type: 'linear', display: true, grid: { color: '#1F2937' }, ticks: { callback: v => fmtTime(v), maxTicksLimit: 8, color: '#64748B' }, title: { display: true, text: 'Elapsed [s]', color: '#64748B' } },
      yP: { type: 'linear', position: 'left',  grid: { color: '#1F2937' }, title: { display: true, text: 'Pressure [mbar]', color: '#64748B' }, beginAtZero: true },
      yF: { type: 'linear', position: 'right', grid: { drawOnChartArea: false }, title: { display: true, text: 'Flow [mL/min]', color: '#64748B' }, beginAtZero: true },
      yV: { type: 'linear', position: 'right', grid: { drawOnChartArea: false }, title: { display: true, text: 'Volume / Loss [mL]', color: '#64748B' }, beginAtZero: true, display: false },
    },
    plugins: { legend: { position: 'top', labels: { boxWidth: 14, font: { size: 10, weight: 'bold' } } } }
  }
});

function fmtTime(s) {
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return m > 0 ? m + 'm' + String(sec).padStart(2,'0') + 's' : sec + 's';
}
function fmtRuntime(s) {
  if (s == null || s <= 0) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), sec = Math.floor(s%60);
  if (h > 0) return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
  return String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
}

function pushPoint(ds, t, v) {
  if (v == null) return;
  ds.data.push({ t: t, v: v });
}

// Load full run history on page load
async function loadHistory() {
  if (!TOKEN) return;
  try {
    const r = await fetch('/history?token=' + encodeURIComponent(TOKEN), { cache: 'no-store' });
    if (!r.ok) return;
    const hist = await r.json();
    for (const p of hist) {
      const t = p.t || 0;
      pushPoint(chart.data.datasets[0], t, p.p1);
      pushPoint(chart.data.datasets[1], t, p.p1s);
      pushPoint(chart.data.datasets[2], t, p.p2);
      pushPoint(chart.data.datasets[3], t, p.fl);
      pushPoint(chart.data.datasets[4], t, p.vol);
      pushPoint(chart.data.datasets[5], t, p.loss);
    }
    chart.update('none');
  } catch(e) {}
}

// ── Phase colors & timeline ──────────────────────────────────────
const PHASE_COLORS = {
  BACKWASH: '#EC4899', FILLING: '#00E5FF',
  PHASE_A: '#8B5CF6', PHASE_B: '#F59E0B', PHASE_B1: '#F59E0B', PHASE_B2: '#10B981',
  PHASE_C: '#EC4899', FINISHED: '#10B981', ABORTED: '#FF1744'
};

function phaseColor(step) {
  for (const [k, c] of Object.entries(PHASE_COLORS)) {
    if ((step || '').includes(k)) return c;
  }
  return '#64748B';
}

function updateTimeline(step) {
  const s = (step || '').toUpperCase();
  const mapping = [
    ['ps_bw',   ['BACKWASH']],
    ['ps_fill', ['FILLING']],
    ['ps_a',    ['PHASE_A']],
    ['ps_b1',   ['PHASE_B1', 'PHASE_B']],
    ['ps_b2',   ['PHASE_B2']],
    ['ps_c',    ['PHASE_C']],
    ['ps_done', ['FINISHED']],
  ];
  const tl = document.getElementById('phase_timeline');
  if (s && s !== 'IDLE') tl.style.display = 'flex'; else tl.style.display = 'none';
  for (const [id, keys] of mapping) {
    const el = document.getElementById(id);
    const matched = keys.some(k => s.includes(k));
    if (matched) {
      el.classList.add('active');
      const c = phaseColor(s);
      el.style.color = c;
      el.style.borderColor = c;
      el.style.background = c + '20';
    } else {
      el.classList.remove('active');
      el.style.color = '';
      el.style.borderColor = '';
      el.style.background = '';
    }
  }
}

// ── UI Update ────────────────────────────────────────────────────
let lastStep = '';
function setDot(state) {
  const d = document.getElementById('conn_dot');
  d.className = 'dot ' + (state === 'live' ? 'live' : state === 'dead' ? 'dead' : '');
}

function updateUI(s) {
  document.getElementById('ts_label').textContent = (s.ts_iso || '').slice(11,19);

  // KPI cards
  document.getElementById('kpi_p1').textContent    = s.p1_meas != null ? Math.round(s.p1_meas) + ' mbar' : '—';
  document.getElementById('kpi_p1s').textContent   = s.p1_set  != null ? 'SET: ' + Math.round(s.p1_set) + ' mbar' : 'SET: —';
  document.getElementById('kpi_p2').textContent    = s.p2_meas != null ? Math.round(s.p2_meas) + ' mbar' : '—';
  document.getElementById('kpi_p2s').textContent   = s.p2_set  != null ? 'SET: ' + Math.round(s.p2_set) + ' mbar' : 'SET: —';
  document.getElementById('kpi_flow').textContent  = s.flow    != null ? s.flow.toFixed(2)   : '—';
  document.getElementById('kpi_vol').textContent   = s.volume_ml != null ? Math.round(s.volume_ml) : '—';
  document.getElementById('kpi_loss').textContent  = (s.loss_ml || 0).toFixed(1) + ' mL';
  document.getElementById('kpi_prog_text').textContent = s.progress_text || '—';
  document.getElementById('kpi_rt').textContent    = fmtRuntime(s.run_elapsed_s);
  document.getElementById('kpi_step').textContent  = s.step || 'IDLE';

  // P1 drift warning
  if (s.p1_set != null && s.p1_meas != null && s.p1_set > 50) {
    const drift = Math.abs(s.p1_meas - s.p1_set) / s.p1_set * 100;
    document.getElementById('kpi_p1s').style.color = drift > 10 ? '#FF1744' : '';
  }

  // Filling banner
  const fb = document.getElementById('filling_banner');
  if ((s.step || '').includes('FILLING')) fb.classList.add('show');
  else fb.classList.remove('show');

  // Phase timeline
  updateTimeline(s.step || '');

  // Progress bar
  const pw = document.getElementById('prog_wrap');
  if (s.phase_label && s.step !== 'IDLE' && s.progress_pct > 0) {
    pw.classList.add('show');
    const c = phaseColor(s.step);
    document.getElementById('prog_phase').textContent = s.phase_label;
    document.getElementById('prog_phase').style.color = c;
    document.getElementById('prog_text').textContent  = s.progress_text || '';
    document.getElementById('prog_fill').style.width  = Math.min(100, Math.max(0, s.progress_pct)) + '%';
    document.getElementById('prog_fill').style.background = c;
  } else {
    pw.classList.remove('show');
  }

  // Status footer
  document.getElementById('s_step').textContent   = s.step   || '—';
  document.getElementById('s_status').textContent = s.status || '—';
  document.getElementById('s_valves').textContent = s.valves || '—';
  document.getElementById('s_loss').textContent   = (s.loss_ml || 0).toFixed(2) + ' mL';
}

// ── SSE live stream ───────────────────────────────────────────────
let sseRetries = 0;
let lastT = -1;

function connectSSE() {
  if (!TOKEN) return;
  const es = new EventSource('/stream?token=' + encodeURIComponent(TOKEN));
  es.onopen = () => { setDot('live'); sseRetries = 0; };
  es.onmessage = (e) => {
    try {
      const s = JSON.parse(e.data);
      updateUI(s);
      // Append new chart point
      const t = s.run_elapsed_s || 0;
      if (t > lastT) {
        lastT = t;
        pushPoint(chart.data.datasets[0], t, s.p1_meas);
        pushPoint(chart.data.datasets[1], t, s.p1_set);
        pushPoint(chart.data.datasets[2], t, s.p2_meas);
        pushPoint(chart.data.datasets[3], t, s.flow);
        pushPoint(chart.data.datasets[4], t, s.volume_ml);
        pushPoint(chart.data.datasets[5], t, s.loss_ml);
        chart.update('none');
      }
    } catch(ex) {}
  };
  es.onerror = () => {
    setDot('dead');
    es.close();
    sseRetries++;
    // Exponential backoff: 2s, 4s, 8s, then cap at 10s
    const delay = Math.min(10000, 2000 * Math.pow(2, Math.min(sseRetries - 1, 3)));
    setTimeout(connectSSE, delay);
  };
}

// Start
loadHistory().then(connectSSE);
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
            server_version = "LittleChonkerMonitor/3.0"

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
                        "version": "3.0",
                        "token_present": bool(token),
                        "note": "Use /status?token=... for JSON status, /stream?token=... for SSE.",
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

                if u.path == "/history":
                    if not self._auth_ok():
                        return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
                    hist = store.get_history()
                    b = json.dumps(hist, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    return self._send(
                        200,
                        b,
                        "application/json; charset=utf-8",
                        extra_headers={"Access-Control-Allow-Origin": "*"},
                    )

                if u.path == "/stream":
                    if not self._auth_ok():
                        return self._send(403, b"Forbidden", "text/plain; charset=utf-8")
                    # Server-Sent Events — keep connection alive
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    try:
                        while True:
                            snap = store.snapshot()
                            data = ("data: " + snap.to_json() + "\n\n").encode("utf-8")
                            self.wfile.write(data)
                            self.wfile.flush()
                            time.sleep(0.3)
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return

                return self._send(404, b"Not Found", "text/plain; charset=utf-8")

            def log_message(self, _format: str, *args: Any) -> None:
                # Suppress stdout spam but forward 4xx/5xx to the module logger
                try:
                    msg = _format % args if args else str(_format)
                    code_str = args[1] if len(args) > 1 else ""
                    if str(code_str).startswith(("4", "5")):
                        logger.warning("MonitorServer HTTP %s — %s", code_str, self.path)
                    else:
                        logger.debug("MonitorServer: %s", msg)
                except Exception:
                    pass

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
        logger.info("MonitorServer v3 started (bind=%s:%s, lan=%s, url=%s)", self.host, self.port, self.lan_ip, self.url())

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

    # ── State update methods ──────────────────────────────────────

    def update_step(self, step: str) -> None:
        s = str(step)
        phase_labels = {
            "BACKWASH":  "PHASE 0: BACKWASH",
            "FILLING":   "PHASE 0: FILLING",
            "PHASE_A":   "PHASE A: RAMP UP",
            "PHASE_B1":  "PHASE B1: STEADY STATE",
            "PHASE_B2":  "PHASE B2: EXTRA DRY",
            "PHASE_B":   "PHASE B: STEADY STATE",
            "PHASE_C":   "PHASE C: RAMP DOWN",
            "FINISHED":  "COMPLETE",
            "ABORTED":   "ABORTED",
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
            volume_ml: Optional[float] = None,
            loss_ml: Optional[float] = None,
            run_elapsed_s: Optional[float] = None,
    ) -> None:
        payload: Dict[str, Any] = {}
        if flow        is not None: payload["flow"]          = float(flow)
        if p1_set      is not None: payload["p1_set"]        = float(p1_set)
        if p1_meas     is not None: payload["p1_meas"]       = float(p1_meas)
        if p2_set      is not None: payload["p2_set"]        = float(p2_set)
        if p2_meas     is not None: payload["p2_meas"]       = float(p2_meas)
        if valves      is not None: payload["valves"]        = str(valves)
        if volume_ml   is not None: payload["volume_ml"]     = float(volume_ml)
        if loss_ml     is not None: payload["loss_ml"]       = float(loss_ml)
        if run_elapsed_s is not None: payload["run_elapsed_s"] = float(run_elapsed_s)
        if payload:
            self._store.update(**payload)

    def write_sample(self, d: dict) -> None:
        """Forward a telemetry sample dict to the history ring buffer."""
        self._store.write_sample(d)
