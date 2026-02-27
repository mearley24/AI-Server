#!/usr/bin/env python3
"""
D-Tools Cloud API Server — REST bridge for Bob and OpenClaw agents.
Runs as a lightweight Flask service inside Docker on Bob (Mac Mini M4).

Endpoints:
  GET  /health              — Health check
  GET  /snapshot            — Quick account overview
  GET  /opportunities       — List opportunities
  GET  /projects            — List projects
  GET  /clients             — List clients
  GET  /catalog?q=keyword   — Search product catalog
  GET  /pipeline            — Active pipeline (open opps + active projects)
  GET  /client/<name>       — Find client and their projects
  POST /opportunity/notes   — Add notes to an opportunity for Bob pickup
"""

import os
import json
from flask import Flask, request, jsonify
from dtools_client import DToolsCloudClient

app = Flask(__name__)

# Initialize client (reads DTOOLS_API_KEY from env)
client = None


def get_client():
    global client
    if client is None:
        client = DToolsCloudClient()
    return client


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.route("/health", methods=["GET"])
def health():
    try:
        c = get_client()
        snap = c.snapshot()
        return jsonify({"status": "healthy", "dtools": snap.get("status", "unknown")})
    except Exception as e:
        return jsonify({"status": "degraded", "error": str(e)}), 500


# ---------------------------------------------------------------------------
# D-Tools Endpoints
# ---------------------------------------------------------------------------
@app.route("/snapshot", methods=["GET"])
def snapshot():
    try:
        return jsonify(get_client().snapshot())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/opportunities", methods=["GET"])
def opportunities():
    try:
        status = request.args.get("status")
        page = int(request.args.get("page", 1))
        return jsonify(get_client().get_opportunities(status=status, page=page))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/projects", methods=["GET"])
def projects():
    try:
        status = request.args.get("status")
        page = int(request.args.get("page", 1))
        return jsonify(get_client().get_projects(status=status, page=page))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/clients", methods=["GET"])
def clients():
    try:
        page = int(request.args.get("page", 1))
        return jsonify(get_client().get_clients(page=page))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/catalog", methods=["GET"])
def catalog():
    try:
        keyword = request.args.get("q", "")
        category = request.args.get("category")
        if not keyword:
            return jsonify({"error": "?q=keyword required"}), 400
        return jsonify(get_client().search_catalog(keyword, category=category))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/pipeline", methods=["GET"])
def pipeline():
    try:
        return jsonify(get_client().get_active_pipeline())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/client/<name>", methods=["GET"])
def find_client(name):
    try:
        return jsonify(get_client().find_client_projects(name))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/opportunity/notes", methods=["POST"])
def update_opp_notes():
    try:
        data = request.get_json()
        opp_id = data.get("opportunity_id")
        notes = data.get("notes", "")
        if not opp_id:
            return jsonify({"error": "opportunity_id required"}), 400
        return jsonify(get_client().mark_opportunity_notes(opp_id, notes))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("DTOOLS_BRIDGE_PORT", "5050"))
    app.run(host="0.0.0.0", port=port, debug=False)
