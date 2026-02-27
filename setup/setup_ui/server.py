#!/usr/bin/env python3
"""
Setup UI Server — One-click setup for Betty (iMac) and Bob (Mac Mini).
Run from any machine:  python3 server.py
Then open http://localhost:8888
"""

import json
import os
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = 8888
REPO_URL = "https://github.com/mearley24/AI-Server.git"
HOME = Path.home()
AI_SERVER = HOME / "AI-Server"


class SetupHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _send_html(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _run(self, cmd, cwd=None, timeout=600):
        """Run command, return (stdout, stderr, exit_code)."""
        try:
            r = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=cwd or HOME,
                timeout=timeout,
                shell=isinstance(cmd, str),
            )
            return (r.stdout or "", r.stderr or "", r.returncode)
        except subprocess.TimeoutExpired:
            return ("", "Command timed out", 124)
        except Exception as e:
            return ("", str(e), 1)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send_html(HTML)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/api/run":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self._send_json({"ok": False, "error": "Invalid JSON"}, 400)
            return

        action = data.get("action", "")
        betty_ip = data.get("betty_ip", "").strip() or os.getenv("BETTY_IP", "192.168.1.132")

        if action == "clone":
            if AI_SERVER.exists():
                out, err, code = (f"{AI_SERVER} already exists.", "", 0)
            else:
                out, err, code = self._run(
                    f"git clone {REPO_URL} {AI_SERVER}",
                    cwd=HOME,
                    timeout=120,
                )
            self._send_json({"ok": code == 0, "stdout": out, "stderr": err, "code": code})
            return

        if action == "harpa":
            script = AI_SERVER / "setup" / "harpa" / "setup_imac_harpa.sh"
            if not script.exists():
                self._send_json({"ok": False, "stderr": f"Run 'clone' first. {script} not found.", "code": 1})
                return
            out, err, code = self._run(
                ["bash", str(script)],
                cwd=AI_SERVER,
                timeout=300,
            )
            self._send_json({"ok": code == 0, "stdout": out, "stderr": err, "code": code})
            return

        if action == "ollama":
            script = AI_SERVER / "setup" / "ollama_worker" / "setup_ollama_worker.sh"
            if not script.exists():
                self._send_json({"ok": False, "stderr": f"Run 'clone' first. {script} not found.", "code": 1})
                return
            out, err, code = self._run(
                ["bash", str(script)],
                cwd=AI_SERVER,
                timeout=900,  # model downloads can be slow
            )
            self._send_json({"ok": code == 0, "stdout": out, "stderr": err, "code": code})
            return

        if action == "verify_ollama":
            out, err, code = self._run(
                f"curl -s --max-time 5 http://{betty_ip}:11434/api/tags",
                timeout=10,
            )
            ok = code == 0 and "models" in (out + err)
            self._send_json({"ok": ok, "stdout": out or err, "stderr": err if out else "", "code": 0 if ok else 1})
            return

        if action == "verify_harpa":
            out, err, code = self._run(
                f"curl -s --max-time 5 http://{betty_ip}:9090/health",
                timeout=10,
            )
            ok = code == 0 and "ok" in (out + err)
            self._send_json({"ok": ok, "stdout": out or err, "stderr": err if out else "", "code": 0 if ok else 1})
            return

        self._send_json({"ok": False, "error": f"Unknown action: {action}"}, 400)


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Symphony Setup — One-Click</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {
      --navy: #0a1628;
      --navy-mid: #132240;
      --gold: #c9a84c;
      --green: #34d399;
      --red: #f87171;
      --text: #d1d5db;
      --gray: #6b7280;
    }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: 'IBM Plex Sans', sans-serif;
      background: var(--navy);
      color: var(--text);
      min-height: 100vh;
      padding: 2rem;
      line-height: 1.6;
    }
    h1 {
      font-size: 1.5rem;
      font-weight: 600;
      margin-bottom: 0.5rem;
      color: #fff;
    }
    .subtitle { color: var(--gray); font-size: 0.9rem; margin-bottom: 2rem; }
    section {
      background: var(--navy-mid);
      border: 1px solid rgba(201,168,76,0.2);
      border-radius: 8px;
      padding: 1.5rem;
      margin-bottom: 1.5rem;
      max-width: 560px;
    }
    section h2 {
      font-size: 1rem;
      font-weight: 600;
      margin-bottom: 1rem;
      color: var(--gold);
    }
    .btn {
      display: inline-block;
      padding: 0.6rem 1.2rem;
      background: var(--gold);
      color: #0a1628;
      border: none;
      border-radius: 6px;
      font-family: inherit;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      margin-right: 0.5rem;
      margin-bottom: 0.5rem;
    }
    .btn:hover { background: #e0c878; }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .btn.secondary { background: rgba(201,168,76,0.3); color: var(--gold); }
    .btn.secondary:hover { background: rgba(201,168,76,0.45); }
    .input-row { margin-bottom: 1rem; }
    .input-row label { display: block; font-size: 0.85rem; color: var(--gray); margin-bottom: 0.25rem; }
    .input-row input {
      width: 100%;
      max-width: 280px;
      padding: 0.5rem 0.75rem;
      background: #060e1a;
      border: 1px solid rgba(201,168,76,0.3);
      border-radius: 6px;
      color: #fff;
      font-family: 'IBM Plex Mono', monospace;
    }
    #log {
      background: #060e1a;
      border: 1px solid rgba(201,168,76,0.2);
      border-radius: 6px;
      padding: 1rem;
      font-family: 'IBM Plex Mono', monospace;
      font-size: 0.8rem;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 300px;
      overflow-y: auto;
      margin-top: 1rem;
      min-height: 80px;
    }
    #log:empty::before { content: 'Output will appear here…'; color: var(--gray); }
    .ok { color: var(--green); }
    .err { color: var(--red); }
    .running { color: var(--gold); }
  </style>
</head>
<body>
  <h1>Symphony Setup</h1>
  <p class="subtitle">Run these steps on the right machine. Output appears below.</p>

  <section>
    <h2>Betty (64GB iMac) — run these on Betty</h2>
    <button class="btn" data-action="clone">1. Clone AI-Server</button>
    <button class="btn" data-action="harpa">2. Run HARPA setup</button>
    <button class="btn" data-action="ollama">3. Run Ollama setup</button>
  </section>

  <section>
    <h2>Bob (Mac Mini) — verify Betty from Bob</h2>
    <div class="input-row">
      <label>Betty's IP address</label>
      <input type="text" id="bettyIp" value="192.168.1.132" placeholder="192.168.1.132">
    </div>
    <button class="btn secondary" data-action="verify_ollama">Verify Ollama</button>
    <button class="btn secondary" data-action="verify_harpa">Verify HARPA bridge</button>
  </section>

  <div id="log"></div>

  <script>
    const logEl = document.getElementById('log');
    const bettyIp = document.getElementById('bettyIp');

    function log(msg, klass) {
      const p = document.createElement('div');
      p.className = klass || '';
      p.textContent = msg;
      logEl.appendChild(p);
      logEl.scrollTop = logEl.scrollHeight;
    }

    function clearLog() {
      logEl.innerHTML = '';
    }

    document.querySelectorAll('.btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const action = btn.dataset.action;
        btn.disabled = true;
        clearLog();
        log('Running: ' + action + '…', 'running');

        try {
          const res = await fetch('/api/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              action,
              betty_ip: bettyIp.value.trim(),
            }),
          });
          const data = await res.json();

          if (data.stdout) log(data.stdout, data.ok ? 'ok' : '');
          if (data.stderr) log(data.stderr, 'err');
          if (!data.stdout && !data.stderr) log(data.error || (data.ok ? 'Done.' : 'Failed.'), data.ok ? 'ok' : 'err');
        } catch (e) {
          log('Error: ' + e.message, 'err');
        }
        btn.disabled = false;
      });
    });
  </script>
</body>
</html>
"""


def main():
    server = HTTPServer(("", PORT), SetupHandler)
    print(f"Symphony Setup UI → http://localhost:{PORT}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
