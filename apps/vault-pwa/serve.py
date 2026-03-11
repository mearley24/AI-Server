#!/usr/bin/env python3
"""Simple HTTP server for the Vault PWA on localhost:8801."""

import http.server
import socketserver
import os

PORT = 8801
HOST = os.environ.get("VAULT_PWA_HOST", "127.0.0.1")
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

os.chdir(DIRECTORY)

class ReuseAddrTCPServer(socketserver.TCPServer):
    allow_reuse_address = True

Handler = http.server.SimpleHTTPRequestHandler

with ReuseAddrTCPServer((HOST, PORT), Handler) as httpd:
    print(f"Vault PWA serving at http://{HOST}:{PORT}")
    httpd.serve_forever()
