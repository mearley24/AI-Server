#!/usr/bin/env python3
"""iMessage bridge — tiny HTTP server that sends iMessages via AppleScript.

Run natively on Bob (NOT in Docker):
    python3 scripts/imessage-server.py

Listens on port 8199 for POST requests with JSON body:
    {"message": "Hello world"}
    {"message": "Hello", "phone": "+1234567890"}
"""

import json
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer

OWNER_PHONE = "+19705193013"
PORT = 8199


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        message = body.get("message", body.get("body", body.get("text", "")))
        phone = body.get("phone", OWNER_PHONE)

        if not message:
            self._respond(400, {"error": "no message"})
            return

        # Escape quotes for AppleScript
        message = message.replace("\\", "\\\\").replace('"', '\\"')

        script = (
            f'tell application "Messages" to send "{message}" '
            f'to buddy "{phone}" of service 1'
        )
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )

        if result.returncode == 0:
            self._respond(200, {"status": "sent", "via": "imessage"})
        else:
            self._respond(500, {"status": "error", "error": result.stderr.strip()})

    def do_GET(self):
        self._respond(200, {"status": "ok", "service": "imessage-bridge"})

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        # Suppress per-request logs; startup message is enough
        pass


if __name__ == "__main__":
    print(f"iMessage bridge listening on port {PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
