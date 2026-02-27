#!/usr/bin/env python3
"""
update_pipeline.py — Remote Ollama model update over Tailscale

Connects to a client node via Tailscale SSH, pushes a new Modelfile,
re-creates the Ollama model, and restarts the service.

Usage:
    python3 update_pipeline.py \\
        --client "The Andersons" \\
        --model-version 2

Requirements:
    pip install paramiko
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

try:
    import paramiko
except ImportError:
    print("[ERROR] paramiko is required: pip install paramiko", file=sys.stderr)
    sys.exit(1)

REGISTRY_PATH = Path(__file__).parent / "client_registry.json"
MODELFILES_DIR = Path(__file__).parent / "modelfiles"
SYMPHONY_SSH_USER = "symphony"


def load_registry() -> dict:
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def find_node(registry: dict, client_name: str) -> dict | None:
    for node in registry["nodes"]:
        if node["client_name"].lower() == client_name.lower():
            return node
    return None


def ssh_run(client: paramiko.SSHClient, cmd: str) -> tuple[int, str, str]:
    """Run a command over SSH, return (exit_code, stdout, stderr)."""
    _, stdout, stderr = client.exec_command(cmd)
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout.read().decode(), stderr.read().decode()


def check_active_sessions(client: paramiko.SSHClient) -> bool:
    """Return True if there are active Ollama sessions (connections to port 11434)."""
    code, out, _ = ssh_run(client, "ss -tn state established '( dport = :11434 )' | grep -c ESTAB || true")
    try:
        count = int(out.strip())
        return count > 0
    except ValueError:
        return False


def update_node(node: dict, model_version: int) -> None:
    client_name  = node["client_name"]
    safe_name    = client_name.lower().replace(" ", "-").replace("—", "").strip("-")
    hostname     = node["tailscale_hostname"]
    model_tag    = f"symphony-{safe_name}:v{model_version}"
    modelfile    = MODELFILES_DIR / f"{client_name.replace(' ', '_')}.Modelfile"

    if not modelfile.exists():
        print(f"[ERROR] Modelfile not found: {modelfile}", file=sys.stderr)
        sys.exit(1)

    print(f"[update] Connecting to {hostname} via Tailscale SSH...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname, username=SYMPHONY_SSH_USER, timeout=15)

    # Check for active sessions
    if check_active_sessions(ssh):
        print("[update] Active sessions detected — waiting 30 seconds before proceeding...")
        import time; time.sleep(30)

    # Upload Modelfile
    remote_path = f"/tmp/{client_name.replace(' ', '_')}.Modelfile"
    print(f"[update] Uploading Modelfile → {remote_path}")
    sftp = ssh.open_sftp()
    sftp.put(str(modelfile), remote_path)
    sftp.close()

    # Create Ollama model
    print(f"[update] Creating Ollama model: {model_tag}")
    code, out, err = ssh_run(ssh, f"docker exec symphony-concierge-ollama ollama create {model_tag} -f {remote_path}")
    if code != 0:
        print(f"[ERROR] ollama create failed:\n{err}", file=sys.stderr)
        sys.exit(1)
    print(out.strip())

    # Restart Nginx (not Ollama — no downtime)
    print("[update] Restarting Nginx...")
    ssh_run(ssh, "cd ~/AI-Server/client_ai && docker compose restart nginx")

    # Update registry
    node["model_version"] = model_version
    node["ollama_model"]   = model_tag
    node["last_updated"]   = datetime.today().date().isoformat()
    print(f"[update] Registry updated — model version: {model_version}")

    ssh.close()
    print(f"[update] Done. {client_name} is now running {model_tag}.")


def main():
    parser = argparse.ArgumentParser(description="Push Ollama model update to a client node.")
    parser.add_argument("--client",        required=True, help="Client name (must match registry)")
    parser.add_argument("--model-version", required=True, type=int, help="New model version number")
    args = parser.parse_args()

    registry = load_registry()
    node = find_node(registry, args.client)
    if not node:
        print(f"[ERROR] Client '{args.client}' not found in registry.", file=sys.stderr)
        sys.exit(1)

    update_node(node, args.model_version)

    # Save updated registry
    with open(REGISTRY_PATH, "w") as f:
        json.dump(registry, f, indent=2)


if __name__ == "__main__":
    main()
