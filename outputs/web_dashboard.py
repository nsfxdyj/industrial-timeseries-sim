"""
Web Dashboard output — real-time HTTP server with SSE streaming.

Serves a built-in HTML dashboard at http://<host>:<port>/
and streams sensor data via Server-Sent Events (SSE) at /events.

Zero extra dependencies: uses only Python standard library
(http.server, threading, queue, json).
"""

import json
import queue
import socket
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


# ---------------------------------------------------------------------------
# HTML Dashboard (embedded so the module stays self-contained)
# ---------------------------------------------------------------------------
_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Industrial Sensor Dashboard</title>
<style>
  :root {
    --bg: #0b0f19;
    --card: #111827;
    --border: #1f2937;
    --text: #e5e7eb;
    --muted: #9ca3af;
    --green: #22c55e;
    --orange: #f59e0b;
    --red: #ef4444;
    --blue: #3b82f6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
  }
  header {
    padding: 1rem 1.5rem;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  header h1 { margin: 0; font-size: 1.25rem; letter-spacing: 0.5px; }
  .status {
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 0.875rem; color: var(--muted);
  }
  .status-dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 1rem;
    padding: 1rem 1.5rem;
  }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem;
    transition: border-color 0.2s;
  }
  .card:hover { border-color: #374151; }
  .card-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 0.5rem;
  }
  .sensor-name { font-weight: 600; font-size: 0.95rem; }
  .sensor-type {
    font-size: 0.75rem; color: var(--muted);
    background: var(--bg); padding: 2px 8px; border-radius: 4px;
  }
  .value-row {
    display: flex; align-items: baseline; gap: 0.5rem;
    margin-bottom: 0.75rem;
  }
  .value {
    font-size: 2rem; font-weight: 700; font-variant-numeric: tabular-nums;
  }
  .unit { font-size: 0.875rem; color: var(--muted); }
  .badge {
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
    padding: 2px 6px; border-radius: 4px;
  }
  .badge.ok { background: rgba(34,197,94,0.15); color: var(--green); }
  .badge.warn { background: rgba(245,158,11,0.15); color: var(--orange); }
  .badge.alarm { background: rgba(239,68,68,0.15); color: var(--red); }
  canvas.sparkline {
    width: 100%; height: 60px;
    background: var(--bg);
    border-radius: 4px;
  }
  .footer {
    text-align: center; padding: 1rem; font-size: 0.75rem; color: var(--muted);
  }
  .meta { font-size: 0.75rem; color: var(--muted); margin-top: 0.25rem; }
</style>
</head>
<body>
<header>
  <h1>🏭 Industrial Sensor Dashboard</h1>
  <div class="status"><span class="status-dot"></span><span id="conn">Live</span></div>
</header>
<div class="grid" id="grid"></div>
<div class="footer">SSE real-time stream • industrial-timeseries-sim</div>
<script>
  const MAX_POINTS = 60;
  const sensors = new Map();
  const grid = document.getElementById('grid');
  const conn = document.getElementById('conn');

  function getColor(value, type) {
    // Simple heuristic thresholds
    if (type === 'temperature') return value > 85 ? 'alarm' : value > 70 ? 'warn' : 'ok';
    if (type === 'pressure') return value < 1 ? 'alarm' : value < 3 ? 'warn' : 'ok';
    if (type === 'vibration') return value > 0.3 ? 'alarm' : value > 0.1 ? 'warn' : 'ok';
    if (type === 'current') return value > 15 ? 'alarm' : value > 10 ? 'warn' : 'ok';
    if (type === 'voltage') return (value < 190 || value > 250) ? 'alarm' : (value < 200 || value > 240) ? 'warn' : 'ok';
    return 'ok';
  }

  function ensureCard(name, type, tags) {
    if (sensors.has(name)) return sensors.get(name);
    const el = document.createElement('div');
    el.className = 'card';
    const unit = tags.unit || '';
    const loc = tags.location || '';
    el.innerHTML = `
      <div class="card-header">
        <span class="sensor-name">${name}</span>
        <span class="sensor-type">${type}</span>
      </div>
      <div class="value-row">
        <span class="value" id="val-${name}">--</span>
        <span class="unit">${unit}</span>
        <span class="badge ok" id="badge-${name}">Normal</span>
      </div>
      <canvas class="sparkline" id="chart-${name}" width="280" height="60"></canvas>
      <div class="meta">${loc ? '📍 ' + loc : ''}</div>
    `;
    grid.appendChild(el);
    const data = { name, type, unit, values: [], el, t0: Date.now() };
    sensors.set(name, data);
    return data;
  }

  function drawSparkline(canvas, values) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (values.length < 2) return;
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    ctx.strokeStyle = '#3b82f6';
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = (i / (MAX_POINTS - 1)) * w;
      const y = h - ((v - min) / range) * (h - 8) - 4;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function update(name, type, value, tags) {
    const s = ensureCard(name, type, tags || {});
    s.values.push(value);
    if (s.values.length > MAX_POINTS) s.values.shift();
    document.getElementById(`val-${name}`).textContent = value.toFixed(3);
    const cls = getColor(value, type);
    const badge = document.getElementById(`badge-${name}`);
    badge.className = 'badge ' + cls;
    badge.textContent = cls === 'ok' ? 'Normal' : cls === 'warn' ? 'Warning' : 'Alarm';
    drawSparkline(document.getElementById(`chart-${name}`), s.values);
  }

  const es = new EventSource('/events');
  es.onmessage = (e) => {
    try {
      const r = JSON.parse(e.data);
      update(r.sensor, r.type || 'unknown', r.value, r.tags);
      conn.textContent = 'Live';
      conn.style.color = 'var(--green)';
    } catch (err) {
      console.error('Parse error', err);
    }
  };
  es.onerror = () => {
    conn.textContent = 'Reconnecting...';
    conn.style.color = 'var(--orange)';
  };
</script>
</body>
</html>
""".strip()


# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------
class _DashboardHandler(BaseHTTPRequestHandler):
    """Handles GET / (dashboard) and GET /events (SSE stream)."""

    # Shared state — injected by WebDashboardOutput
    _sse_queues = []          # list of queue.Queue
    _sse_lock = None          # threading.Lock
    _sensor_types = {}        # sensor_name -> type (injected on first write)

    def log_message(self, fmt, *args):
        # Suppress default access logs to keep console clean
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_dashboard()
        elif self.path == "/events":
            self._serve_sse()
        else:
            self.send_error(404, "Not found")

    def _serve_dashboard(self):
        body = _DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q = queue.Queue(maxsize=256)
        with self._sse_lock:
            self._sse_queues.append(q)

        # Send an initial comment to confirm connection
        self.wfile.write(b":ok\n\n")
        self.wfile.flush()

        try:
            while True:
                payload = q.get(timeout=30)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except queue.Empty:
            # Client idle timeout — close gracefully
            pass
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with self._sse_lock:
                if q in self._sse_queues:
                    self._sse_queues.remove(q)


# ---------------------------------------------------------------------------
# Output adapter
# ---------------------------------------------------------------------------
class WebDashboardOutput:
    """
    Real-time web dashboard output.

    Parameters (from YAML):
        host  — HTTP bind address (default "0.0.0.0")
        port  — HTTP port (default 8080)

    Usage:
        outputs:
          - type: web_dashboard
            port: 8080

    Then open http://localhost:8080 in your browser.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = int(port)
        self._server = None
        self._thread = None
        self._queues = []
        self._lock = threading.Lock()
        self._sensor_types = {}

    def open(self):
        # Inject shared state into handler class
        _DashboardHandler._sse_queues = self._queues
        _DashboardHandler._sse_lock = self._lock
        _DashboardHandler._sensor_types = self._sensor_types

        self._server = HTTPServer((self.host, self.port), _DashboardHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[WebDashboard] Serving at http://{self.host}:{self.port}/")

    def write(self, record: dict):
        # Enrich record with sensor type if known
        sensor = record["sensor"]
        if sensor not in self._sensor_types:
            # Infer type from tags if present, else "unknown"
            tags = record.get("tags", {})
            inferred = tags.get("_type", "unknown")
            self._sensor_types[sensor] = inferred

        # Build SSE payload
        payload = {
            "timestamp": record["timestamp"],
            "sensor": sensor,
            "value": record["value"],
            "tags": record.get("tags", {}),
            "type": self._sensor_types.get(sensor, "unknown"),
        }
        data = json.dumps(payload, ensure_ascii=False)

        # Broadcast to all connected SSE clients
        with self._lock:
            # Clean up dead queues (clients that disconnected)
            dead = []
            for q in self._queues:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    dead.append(q)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._queues.remove(q)

    def close(self):
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=3.0)
        print("[WebDashboard] Server stopped.")

    def _find_free_port(self, start: int = 8080) -> int:
        """Find an available TCP port starting from *start*."""
        for p in range(start, start + 100):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", p)) != 0:
                    return p
        raise RuntimeError("No free port found")
