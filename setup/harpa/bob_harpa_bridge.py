#!/usr/bin/env python3
"""
bob_harpa_bridge.py
Symphony Smart Homes — Bob's HARPA Grid API Bridge

Runs on Mac Mini M4 (Bob the Conductor).
Provides an HTTP API that OpenClaw can call to execute D-Tools Cloud automation
via HARPA AI running on the Intel iMac browser nodes.

Architecture:
  OpenClaw (Bob) → bob_harpa_bridge.py (this) → HARPA Grid API (iMac Chrome)

Usage:
  python3 bob_harpa_bridge.py
  python3 bob_harpa_bridge.py --host 0.0.0.0 --port 9090  # LAN accessible
  python3 bob_harpa_bridge.py --config /path/to/config.json

Endpoints:
  GET  /health                  — Health check
  GET  /status                  — Status + HARPA node availability
  POST /automation/run          — Run a HARPA command
  POST /automation/create_project
  POST /automation/import_equipment_csv
  POST /automation/get_project_status
  POST /automation/export_proposal
  POST /automation/update_project_phase
  POST /automation/search_projects

Configuration:
  Set environment variables or edit DEFAULTS below.
  Do NOT commit real API keys — use environment variables.

Environment variables:
  HARPA_GRID_URL        Base URL of HARPA Grid API on iMac (e.g., http://192.168.1.50:8765)
  HARPA_GRID_API_KEY    HARPA Grid API key from HARPA Settings > Grid
  BRIDGE_HOST           Host to bind bridge server (default: 127.0.0.1)
  BRIDGE_PORT           Port for bridge server (default: 9090)
  HARPA_TIMEOUT         Timeout for HARPA requests in seconds (default: 60)
"""

import os
import json
import time
import logging
import argparse
import threading
from datetime import datetime
from functools import wraps
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urljoin

# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULTS = {
    # HARPA Grid API endpoint on the iMac
    # Replace with actual iMac IP after running setup_imac_harpa.sh
    "harpa_grid_url": os.getenv("HARPA_GRID_URL", "http://YOUR_IMAC_IP:8765"),

    # HARPA Grid API key from HARPA Settings > Grid
    # Get this from the iMac after HARPA Grid is enabled
    "harpa_grid_api_key": os.getenv("HARPA_GRID_API_KEY", "YOUR_HARPA_GRID_API_KEY"),

    # Bridge server binding
    "bridge_host": os.getenv("BRIDGE_HOST", "127.0.0.1"),  # localhost only
    "bridge_port": int(os.getenv("BRIDGE_PORT", "9090")),

    # Request timeouts
    "harpa_timeout": int(os.getenv("HARPA_TIMEOUT", "60")),
    "harpa_long_timeout": int(os.getenv("HARPA_LONG_TIMEOUT", "120")),

    # Logging
    "log_level": os.getenv("LOG_LEVEL", "INFO"),
    "log_file": os.getenv("LOG_FILE", os.path.expanduser("~/.openclaw/logs/harpa_bridge.log")),
}

# =============================================================================
# LOGGING
# =============================================================================

def setup_logging(level: str, log_file: str) -> logging.Logger:
    """Configure logging to both console and file."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    log_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(formatter)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger("harpa_bridge")
    logger.setLevel(log_level)
    logger.addHandler(console)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging(DEFAULTS["log_level"], DEFAULTS["log_file"])

# =============================================================================
# HARPA GRID CLIENT
# =============================================================================

class HARPAGridClient:
    """
    Client for the HARPA Grid API.
    HARPA Grid exposes a local HTTP endpoint that accepts commands
    and executes them in the Chrome browser with HARPA installed.
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._last_check: float = 0
        self._is_available: bool = False

    def _make_request(self, method: str, path: str, data: dict = None, timeout: int = None) -> dict:
        """Make an HTTP request to the HARPA Grid API."""
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        timeout = timeout or self.timeout

        headers = {
            "Content-Type": "application/json",
            "X-HARPA-Key": self.api_key,
        }

        body = json.dumps(data).encode("utf-8") if data else None

        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(f"HARPA API HTTP {e.code}: {e.reason}. Body: {error_body}")
        except URLError as e:
            raise RuntimeError(f"HARPA API connection failed: {e.reason}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"HARPA API returned invalid JSON: {e}")

    def health_check(self) -> bool:
        """Check if HARPA Grid is available."""
        # Cache health check for 30 seconds
        now = time.time()
        if now - self._last_check < 30:
            return self._is_available

        try:
            self._make_request("GET", "/health", timeout=5)
            self._is_available = True
        except Exception:
            self._is_available = False

        self._last_check = now
        return self._is_available

    def run_command(self, command_name: str, variables: dict = None, timeout: int = None) -> dict:
        """
        Execute a named HARPA command.

        Args:
            command_name: The HARPA command ID (matches commands in harpa_dtools_commands.json)
            variables: Variables to pass to the command
            timeout: Override default timeout for long-running commands

        Returns:
            dict with 'success', 'result', and optionally 'error' keys
        """
        payload = {
            "command": command_name,
            "variables": variables or {},
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }

        logger.info(f"Executing HARPA command: {command_name} | vars: {list((variables or {}).keys())}")

        try:
            result = self._make_request("POST", "/run", data=payload, timeout=timeout)
            logger.info(f"HARPA command {command_name}: success")
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"HARPA command {command_name} failed: {e}")
            return {"success": False, "error": str(e), "result": None}


# =============================================================================
# BRIDGE HANDLER
# =============================================================================

class BridgeHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for the Bob HARPA Bridge.
    Receives requests from OpenClaw and forwards them to HARPA.
    """

    harpa: HARPAGridClient = None  # Set at server startup

    def log_message(self, fmt, *args):
        logger.debug(f"HTTP: {fmt}" % args)

    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "ok",
                "service": "bob_harpa_bridge",
                "timestamp": datetime.utcnow().isoformat() + "Z",
            })

        elif self.path == "/status":
            harpa_available = self.harpa.health_check() if self.harpa else False
            self._send_json(200, {
                "bridge": "running",
                "harpa_node": "available" if harpa_available else "unavailable",
                "harpa_url": self.harpa.base_url if self.harpa else None,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            })

        else:
            self._send_json(404, {"error": f"Unknown path: {self.path}"})

    def do_POST(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"Invalid JSON body: {e}"})
            return

        if self.path == "/automation/run":
            # Generic: {"command": "...", "variables": {...}}
            command = body.get("command")
            if not command:
                self._send_json(400, {"error": "'command' field required"})
                return
            result = self.harpa.run_command(command, body.get("variables", {}))
            status = 200 if result["success"] else 502
            self._send_json(status, result)

        elif self.path == "/automation/create_project":
            result = self.harpa.run_command(
                "dtools_create_project",
                {
                    "client_name": body.get("client_name", ""),
                    "project_name": body.get("project_name", ""),
                    "address": body.get("address", ""),
                    "project_type": body.get("project_type", "Residential"),
                    "notes": body.get("notes", ""),
                },
                timeout=DEFAULTS["harpa_long_timeout"]
            )
            status = 200 if result["success"] else 502
            self._send_json(status, result)

        elif self.path == "/automation/import_equipment_csv":
            result = self.harpa.run_command(
                "dtools_import_equipment_csv",
                {
                    "project_name": body.get("project_name", ""),
                    "csv_content": body.get("csv_content", ""),
                    "csv_filename": body.get("csv_filename", "equipment.csv"),
                },
                timeout=DEFAULTS["harpa_long_timeout"]
            )
            status = 200 if result["success"] else 502
            self._send_json(status, result)

        elif self.path == "/automation/get_project_status":
            result = self.harpa.run_command(
                "dtools_get_project_status",
                {"project_name": body.get("project_name", "")},
                timeout=DEFAULTS["harpa_timeout"]
            )
            status = 200 if result["success"] else 502
            self._send_json(status, result)

        elif self.path == "/automation/export_proposal":
            result = self.harpa.run_command(
                "dtools_export_proposal",
                {
                    "project_name": body.get("project_name", ""),
                    "export_format": body.get("export_format", "PDF"),
                },
                timeout=DEFAULTS["harpa_long_timeout"]
            )
            status = 200 if result["success"] else 502
            self._send_json(status, result)

        elif self.path == "/automation/update_project_phase":
            result = self.harpa.run_command(
                "dtools_update_project_phase",
                {
                    "project_name": body.get("project_name", ""),
                    "new_phase": body.get("new_phase", ""),
                    "notes": body.get("notes", ""),
                },
                timeout=DEFAULTS["harpa_timeout"]
            )
            status = 200 if result["success"] else 502
            self._send_json(status, result)

        elif self.path == "/automation/search_projects":
            result = self.harpa.run_command(
                "dtools_search_projects",
                {"search_term": body.get("search_term", "")},
                timeout=DEFAULTS["harpa_timeout"]
            )
            status = 200 if result["success"] else 502
            self._send_json(status, result)

        else:
            self._send_json(404, {"error": f"Unknown endpoint: {self.path}"})


# =============================================================================
# MAIN
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(description="Bob HARPA Bridge API Server")
    parser.add_argument("--host", default=DEFAULTS["bridge_host"],
                        help=f"Bind host (default: {DEFAULTS['bridge_host']})")
    parser.add_argument("--port", type=int, default=DEFAULTS["bridge_port"],
                        help=f"Bind port (default: {DEFAULTS['bridge_port']})")
    parser.add_argument("--harpa-url", default=DEFAULTS["harpa_grid_url"],
                        help="HARPA Grid API URL on iMac")
    parser.add_argument("--harpa-key", default=DEFAULTS["harpa_grid_api_key"],
                        help="HARPA Grid API key")
    parser.add_argument("--config", default=None,
                        help="Path to JSON config file (overrides defaults)")
    return parser.parse_args()


def load_config(config_path: str) -> dict:
    if not config_path or not os.path.exists(config_path):
        return {}
    with open(config_path) as f:
        return json.load(f)


def main():
    args = parse_args()

    # Load optional config file
    file_config = load_config(args.config)

    # Merge: defaults < file config < CLI args
    harpa_url = file_config.get("harpa_grid_url", args.harpa_url)
    harpa_key = file_config.get("harpa_grid_api_key", args.harpa_key)
    host = file_config.get("bridge_host", args.host)
    port = file_config.get("bridge_port", args.port)

    # Warn about placeholders
    if "YOUR_" in harpa_url:
        logger.warning(
            "HARPA_GRID_URL still contains placeholder. "
            "Set HARPA_GRID_URL env var or use --harpa-url flag."
        )
    if "YOUR_" in harpa_key:
        logger.warning(
            "HARPA_GRID_API_KEY still contains placeholder. "
            "Set HARPA_GRID_API_KEY env var or use --harpa-key flag."
        )

    # Create HARPA client
    harpa = HARPAGridClient(
        base_url=harpa_url,
        api_key=harpa_key,
        timeout=DEFAULTS["harpa_timeout"]
    )

    # Inject into handler class
    BridgeHandler.harpa = harpa

    # Start server
    server = HTTPServer((host, port), BridgeHandler)

    logger.info(f"Bob HARPA Bridge starting on http://{host}:{port}")
    logger.info(f"HARPA Grid target: {harpa_url}")
    logger.info("Endpoints:")
    logger.info("  GET  /health")
    logger.info("  GET  /status")
    logger.info("  POST /automation/run")
    logger.info("  POST /automation/create_project")
    logger.info("  POST /automation/import_equipment_csv")
    logger.info("  POST /automation/get_project_status")
    logger.info("  POST /automation/export_proposal")
    logger.info("  POST /automation/update_project_phase")
    logger.info("  POST /automation/search_projects")

    # Initial health check
    threading.Thread(
        target=lambda: logger.info(
            f"HARPA node status: {'available' if harpa.health_check() else 'unavailable (check HARPA Grid on iMac)'}"
        ),
        daemon=True
    ).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Bridge server stopped.")
        server.server_close()


if __name__ == "__main__":
    main()


# =============================================================================
# USAGE EXAMPLES
# =============================================================================
#
# 1. Start the bridge:
#    python3 bob_harpa_bridge.py
#
# 2. Check health:
#    curl http://localhost:9090/health
#
# 3. Check HARPA node status:
#    curl http://localhost:9090/status
#
# 4. Create a D-Tools project:
#    curl -X POST http://localhost:9090/automation/create_project \
#      -H 'Content-Type: application/json' \
#      -d '{
#        "client_name": "Smith, John",
#        "project_name": "Smith Residence - 2024",
#        "address": "123 Main St, Denver CO 80201",
#        "project_type": "Residential",
#        "notes": "New construction, 4200 sq ft"
#      }'
#
# 5. Get project status:
#    curl -X POST http://localhost:9090/automation/get_project_status \
#      -H 'Content-Type: application/json' \
#      -d '{"project_name": "Smith Residence - 2024"}'
#
# 6. Search projects:
#    curl -X POST http://localhost:9090/automation/search_projects \
#      -H 'Content-Type: application/json' \
#      -d '{"search_term": "Smith"}'
#
# 7. Import equipment CSV:
#    CSV_CONTENT=$(cat equipment.csv)
#    curl -X POST http://localhost:9090/automation/import_equipment_csv \
#      -H 'Content-Type: application/json' \
#      -d "{\"project_name\": \"Smith Residence - 2024\", \"csv_content\": \"$CSV_CONTENT\"}"
#
# =============================================================================
