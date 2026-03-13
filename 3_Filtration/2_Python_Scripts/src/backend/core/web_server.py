import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PySide6.QtCore import QThread, Signal
import threading

# Globaler, Thread-sicherer Speicher für Sensordaten
_telemetry_state = {}
_state_lock = threading.Lock()

def update_web_telemetry(sample: dict):
    """Wird vom Main Window aufgerufen, um die neuesten Daten einzuspeisen."""
    global _telemetry_state
    with _state_lock:
        _telemetry_state = sample

class TelemetryHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Verhindert, dass das Terminal vollgespammt wird

    def do_GET(self):
        # 1. API Route (Liefert NUR die reinen JSON-Daten)
        if self.path == '/api/data':
            with _state_lock:
                data = json.dumps(_telemetry_state).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            # Zwingt den Browser, die Daten NIEMALS zwischenzuspeichern:
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            
        # 2. Hauptseite (Liefert das schicke Dashboard)
        elif self.path == '/' or self.path == '/index.html':
            html = """<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
                <title>CHONKER // COMMAND</title>
                <style>
                    * { box-sizing: border-box; }
                    body { background-color: #0B1120; color: #F8FAFC; font-family: 'Consolas', 'Courier New', monospace; margin: 0; padding: 20px; }
                    .header { text-align: center; margin-bottom: 30px; }
                    .header h1 { color: #F8FAFC; font-size: 20px; letter-spacing: 3px; margin: 0 0 5px 0; }
                    .conn-status { font-size: 12px; color: #10B981; font-weight: bold; }
                    .conn-status.offline { color: #FF1744; }
                    
                    .state-box { background: #111827; border: 1px solid #1E293B; border-top: 3px solid #00E5FF; padding: 15px; border-radius: 6px; text-align: center; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
                    .state-lbl { font-size: 11px; color: #94A3B8; margin-bottom: 5px; font-weight: bold; letter-spacing: 1px;}
                    .state-val { font-size: 24px; font-weight: bold; color: #00E5FF; }

                    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
                    .card { background: #0F172A; border: 1px solid #1E293B; padding: 15px 10px; border-radius: 6px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); }
                    
                    .card.cyan { border-top: 3px solid #00E5FF; }
                    .card.purple { border-top: 3px solid #8B5CF6; }
                    .card.green { border-top: 3px solid #10B981; }
                    .card.pink { border-top: 3px solid #EC4899; }
                    
                    .lbl { font-size: 11px; color: #94A3B8; font-weight: bold; letter-spacing: 1px; margin-bottom: 8px; }
                    .val { font-size: 22px; font-weight: bold; }
                    
                    .footer { text-align: center; margin-top: 40px; font-size: 10px; color: #334155; }
                </style>
            </head>
            <body>
                <div class="header">
                    <h1>LITTLE CHONKER</h1>
                    <div id="conn_indicator" class="conn-status">● LIVE CONNECTION</div>
                </div>

                <div class="state-box">
                    <div class="state-lbl">CURRENT STATE</div>
                    <div class="state-val" id="step">WAITING...</div>
                </div>

                <div class="grid">
                    <div class="card cyan">
                        <div class="lbl">MAIN (mbar)</div>
                        <div class="val" id="p1" style="color:#00E5FF;">0</div>
                    </div>
                    <div class="card purple">
                        <div class="lbl">BACKWASH (mbar)</div>
                        <div class="val" id="p2" style="color:#8B5CF6;">0</div>
                    </div>
                    <div class="card green">
                        <div class="lbl">FLOW (mL/min)</div>
                        <div class="val" id="flow" style="color:#10B981;">0.000</div>
                    </div>
                    <div class="card pink">
                        <div class="lbl">LOSS (mL)</div>
                        <div class="val" id="loss" style="color:#EC4899;">0.00</div>
                    </div>
                </div>

                <div class="footer">REMOTE TELEMETRY NODE</div>

                <script>
                    const ind = document.getElementById('conn_indicator');
                    
                    function update() {
                        fetch('/api/data', { cache: "no-store" })
                            .then(response => {
                                if(!response.ok) throw new Error("Network response was not ok");
                                return response.json();
                            })
                            .then(data => {
                                ind.innerText = "● LIVE CONNECTION";
                                ind.className = "conn-status";
                                
                                document.getElementById('step').innerText = data.step || "IDLE";
                                
                                let p1 = 0, p2 = 0;
                                if(data.pressure && data.pressure['1']) p1 = data.pressure['1'].meas || 0;
                                else p1 = data.p1_meas || 0;
                                
                                if(data.pressure && data.pressure['2']) p2 = data.pressure['2'].meas || 0;
                                else p2 = data.p2_meas || 0;

                                document.getElementById('p1').innerText = Math.round(p1);
                                document.getElementById('p2').innerText = Math.round(p2);
                                document.getElementById('flow').innerText = (data.flow || 0).toFixed(3);
                                document.getElementById('loss').innerText = (data.loss_ml || 0).toFixed(2);
                            })
                            .catch(err => {
                                ind.innerText = "● CONNECTION LOST";
                                ind.className = "conn-status offline";
                            });
                    }
                    // Holt alle 500ms neue Daten
                    setInterval(update, 500); 
                    update(); // Einmal sofort beim Laden ausführen
                </script>
            </body>
            </html>"""
            html_bytes = html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.send_header('Content-Length', str(len(html_bytes)))
            # Verhindert, dass das Handy die Seite aus dem Cache lädt
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.end_headers()
            self.wfile.write(html_bytes)
            
        # 3. Alle anderen Anfragen (z.B. favicon.ico) sauber abblocken
        else:
            self.send_response(404)
            self.end_headers()

# =========================================================================
# QTHREAD SERVER (Crash-Proof)
# =========================================================================
class ServerWorker(QThread):
    started_signal = Signal(int)
    error_signal = Signal(str)

    def __init__(self, port):
        super().__init__()
        self.port = port
        self.server = None

    def run(self):
        try:
            self.server = ThreadingHTTPServer(('0.0.0.0', self.port), TelemetryHandler)
            self.started_signal.emit(self.port)
            self.server.serve_forever()
        except Exception as e:
            self.error_signal.emit(str(e))

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()

class TelemetryWebServer:
    def __init__(self, port=8000):
        self.port = port
        self.worker = None

    def start(self):
        if self.worker is not None and self.worker.isRunning():
            return
        
        self.worker = ServerWorker(self.port)
        self.worker.started_signal.connect(lambda p: print(f">>> WEB SERVER RUNNING ON PORT {p} (0.0.0.0) <<<"))
        self.worker.error_signal.connect(lambda e: print(f"!!! WEB SERVER CRASHED: {e} !!!"))
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None
            print(">>> WEB SERVER STOPPED <<<")