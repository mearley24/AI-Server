#!/usr/bin/env python3
"""
Symphony Markup App Server

Serves the iPad markup tool and handles export/import.

Usage:
    python3 server.py                              # Start on localhost:8091
    python3 server.py --host 127.0.0.1 --port 8091  # Custom bind/port

For HTTPS (Share → Save to Files on iPad): tailscale serve 8091, set MARKUP_HTTPS_URL in .env
"""

import argparse
import json
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
import socket
import mimetypes
from urllib.parse import parse_qs, urlsplit

# Load .env from AI-Server root
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

BASE = Path(__file__).parent
WEB_DIR = BASE / "web"

# Save to iCloud so iPad can access, and also local for Bob
ICLOUD_EXPORTS = Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Symphony SH" / "Markup_Exports"
LOCAL_EXPORTS = Path.home() / "AI-Server" / "knowledge" / "markup_exports"
ICLOUD_EXPORTS.mkdir(parents=True, exist_ok=True)
LOCAL_EXPORTS.mkdir(parents=True, exist_ok=True)


class MarkupHandler(BaseHTTPRequestHandler):
    """Custom handler for markup app."""

    @staticmethod
    def _slugify_name(value: str) -> str:
        """Normalize project/file names for safe filesystem paths."""
        cleaned = (value or "untitled").strip().replace(" ", "_").replace("/", "-")
        cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in ("-", "_", "."))
        return cleaned or "untitled"

    def _resolve_save_target(self, data: dict) -> tuple[str, str]:
        """
        Resolve (project_folder, filename) for save operations.

        Supports:
        - savePath: "Project/file.symphony" for overwriting canonical project file
        - default behavior: timestamped snapshot in project folder
        """
        project = self._slugify_name(data.get('project') or data.get('projectName') or 'untitled')
        save_path = str(data.get('savePath') or '').strip()
        if save_path:
            raw = Path(save_path.replace("\\", "/"))
            parts = [self._slugify_name(p) for p in raw.parts if p not in ("", ".", "..")]
            if parts:
                if len(parts) == 1:
                    filename = parts[0]
                    if "." not in filename:
                        filename = f"{filename}.symphony"
                    return project, filename
                folder = parts[0] or project
                filename = parts[-1]
                if "." not in filename:
                    filename = f"{filename}.symphony"
                return folder, filename

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{project}_{timestamp}.symphony"
        return project, filename

    def _list_project_folders(self, query: str = "", limit: int = 200) -> list[str]:
        """List known project folders from iCloud/local export roots."""
        folders = set()
        for root in (ICLOUD_EXPORTS, LOCAL_EXPORTS):
            if not root.exists():
                continue
            for entry in root.iterdir():
                if entry.is_dir():
                    folders.add(entry.name)

        names = sorted(folders, key=lambda s: s.lower())
        q = (query or "").strip().lower()
        if q:
            tokens = [t for t in q.replace("_", " ").replace("-", " ").split() if t]
            filtered: list[str] = []
            for name in names:
                lower = name.lower()
                if q in lower or all(t in lower for t in tokens):
                    filtered.append(name)
            names = filtered
        return names[: max(1, min(limit, 1000))]
    
    def do_GET(self):
        """Serve static files and /api/config."""
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query)

        if path == '/api/config':
            https_url = os.environ.get("MARKUP_HTTPS_URL", "").strip()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"httpsUrl": https_url or None}).encode())
            return

        if path == '/api/folders':
            q = (query.get("query", [""])[0] or "").strip()
            try:
                limit = int(query.get("limit", ["200"])[0])
            except (TypeError, ValueError):
                limit = 200
            folders = self._list_project_folders(query=q, limit=limit)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": True,
                "query": q,
                "count": len(folders),
                "folders": folders,
            }).encode())
            return

        if path == '/' or path == '':
            path = '/index.html'

        filepath = WEB_DIR / path.lstrip('/')
        
        if filepath.exists() and filepath.is_file():
            content_type, _ = mimetypes.guess_type(str(filepath))
            if content_type is None:
                content_type = 'application/octet-stream'
            
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Access-Control-Allow-Origin', '*')
            # Avoid stale PWA UI after deploys (especially index + service worker).
            rel = filepath.relative_to(WEB_DIR).as_posix()
            if rel in {"index.html", "sw.js"}:
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
            self.end_headers()
            
            with open(filepath, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h1>404 Not Found</h1>')
    
    def do_POST(self):
        """Handle POST requests for saving markups."""
        if self.path == '/api/save':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data)
                project, filename = self._resolve_save_target(data)
                
                # Save to project subfolder (so files are organized by project)
                icloud_dir = ICLOUD_EXPORTS / project
                local_dir = LOCAL_EXPORTS / project
                icloud_dir.mkdir(parents=True, exist_ok=True)
                local_dir.mkdir(parents=True, exist_ok=True)
                icloud_path = icloud_dir / filename
                local_path = local_dir / filename
                
                with open(icloud_path, 'w') as f:
                    json.dump(data, f, indent=2)
                with open(local_path, 'w') as f:
                    json.dump(data, f, indent=2)
                
                rel_path = f"{project}/{filename}"
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'filename': rel_path,
                    'savePath': rel_path,
                    'icloud': str(icloud_path),
                    'local': str(local_path)
                }).encode())
                
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def log_message(self, format, *args):
        """Quieter logging."""
        pass


def get_local_ip():
    """Get local IP address for LAN access."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "localhost"


def main():
    parser = argparse.ArgumentParser(description="Symphony Markup App Server")
    parser.add_argument('--port', type=int, default=8091, help='Port number')
    parser.add_argument('--host', default='127.0.0.1', help='Host/IP to bind (default: localhost)')
    args = parser.parse_args()
    
    local_ip = get_local_ip()
    
    remote_hint = f"║  LAN:    http://{local_ip}:{args.port}                        ║" if args.host == "0.0.0.0" else "║  LAN:    disabled (localhost bind)                      ║"

    print(f"""
╔════════════════════════════════════════════════════════════╗
║             Symphony Markup App Server                     ║
╠════════════════════════════════════════════════════════════╣
║  Bind:   {args.host:<43}║
║  Local:  http://localhost:{args.port:<25}║
{remote_hint}
╠════════════════════════════════════════════════════════════╣
║  Exports saved to:                                         ║
║    iCloud: ~/Library/.../Symphony SH/Markup_Exports/       ║
║    Local:  ~/AI-Server/knowledge/markup_exports/           ║
╚════════════════════════════════════════════════════════════╝
Press Ctrl+C to stop
    """)
    
    server = HTTPServer((args.host, args.port), MarkupHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
