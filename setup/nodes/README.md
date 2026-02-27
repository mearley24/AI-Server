# Symphony Smart Homes — Node Infrastructure

> AI network node management for the Symphony Smart Homes AI platform.
> Lives at `setup/nodes/` in the AI-Server repo.

---

## Architecture

```
                        ┌─────────────────────────────────────────────────────┐
                        │              SYMPHONY AI NETWORK                    │
                        │                                                     │
                        │  ┌───────────────────────────────────────────────┐  │
                        │  │         BOB  (Mac Mini M4 — HQ)              │  │
                        │  │                                               │  │
                        │  │  ┌─────────────┐  ┌──────────────────────┐   │  │
                        │  │  │  OpenClaw   │  │   Node Health        │   │  │
                        │  │  │  (Conductor)│  │   Monitor            │   │  │
                        │  │  └──────┬──────┘  └──────────┬───────────┘   │  │
                        │  │         │                     │               │  │
                        │  │  ┌──────▼──────────────────────────────────┐  │  │
                        │  │  │  nodes_registry.json  /  openclaw_      │  │  │
                        │  │  │  workers.json  (Bob reads these)        │  │  │
                        │  │  └──────────────────────────────────────────┘  │  │
                        │  │                                               │  │
                        │  │  ┌──────────────────────────────────────┐    │  │
                        │  │  │  Ollama (3B routing, embeddings)     │    │  │
                        │  │  │  Docker  │  Registry API (:8765)     │    │  │
                        │  │  └──────────────────────────────────────┘    │  │
                        │  └───────────────────────────────────────────────┘  │
                        │           │ LAN  │               │ LAN              │
                        │    ───────┴──────┴───────────────┴───────           │
                        │           │                      │                  │
                        │  ┌────────▼───────────┐ ┌────────▼──────────┐      │
                        │  │  MAESTRO           │ │  STAGEHAND        │      │
                        │  │  Intel iMac 2019   │ │  Intel iMac       │      │
                        │  │  64GB RAM          │ │  8GB RAM          │      │
                        │  │                    │ │                   │      │
                        │  │  Ollama (:11434)   │ │  Chrome + HARPA   │      │
                        │  │  ├ llama3.1:8b     │ │  D-Tools Cloud    │      │
                        │  │  ├ llama3.1:70b    │ │  Browser sessions │      │
                        │  │  └ mistral:7b      │ │                   │      │
                        │  │  HARPA (Chrome)    │ │                   │      │
                        │  │  CPU-only mode     │ │  (no LLM — 8GB)   │      │
                        │  └────────────────────┘ └───────────────────┘      │
                        │                                                     │
                        │  ┌─────────────────────────────────────────────┐   │
                        │  │  FUTURE WORKERS (Apple Silicon)             │   │
                        │  │                                             │   │
                        │  │  Mac Mini M4   →  llm_worker (24GB+)       │   │
                        │  │  Mac Mini M4 Pro → full_worker (48GB)      │   │
                        │  │  Mac Studio M4 Max → power node (64-192GB) │   │
                        │  │                                             │   │
                        │  │  All get: Metal GPU accel, MLX, Ollama,    │   │
                        │  │  Docker, optional HARPA                    │   │
                        │  └─────────────────────────────────────────────┘   │
                        └─────────────────────────────────────────────────────┘

  ROUTING FLOW:
  OpenClaw receives task → reads openclaw_workers.json routing rules
      → classifies task type → selects worker by priority + availability
      → sends to Ollama API (local) or HARPA Grid (browser) or Cloud API (fallback)
```

---

## File Manifest

| File | Purpose | Read By |
|------|---------|---------|  
| `nodes_registry.json` | Registry of all nodes — IPs, hardware, services, status | Bob (health monitor, OpenClaw), `provision_node.sh` |
| `provision_node.sh` | Bash script to bootstrap a new macOS node | Run on each new node |
| `node_health_monitor.py` | Python daemon on Bob — polls all nodes, outputs dashboard or JSON | Bob (cron), OpenClaw |
| `openclaw_workers.json` | Worker config for OpenClaw — routing rules, endpoints, priorities | OpenClaw on Bob |
| `add_node_guide.md` | Step-by-step guide for adding a new node (hardware → running) | Humans |
| `imac_reset_guide.md` | Quick reset guide for Maestro & Stagehand specifically | Humans |
| `README.md` | This file — overview and quick reference | Humans |

---

## Quick Start: Adding a New Node

```bash
# 1. Reset the Mac (see imac_reset_guide.md or add_node_guide.md §3)

# 2. Copy provision script to the new Mac
scp setup/nodes/provision_node.sh symphony@newnode.local:~/

# 3. SSH in and run
ssh symphony@newnode.local
chmod +x provision_node.sh
./provision_node.sh --hostname virtuoso --role full_worker --bob-ip 192.168.1.10

# 4. Verify from Bob
python3 ~/.symphony/node_health_monitor.py
curl http://virtuoso.local:11434/api/tags

# 5. Update openclaw_workers.json on Bob with the new worker entry
# 6. Reload OpenClaw worker config
```

---

## Node Roles

| Role | Services | Use Case |
|------|----------|----------|
| `hq` | OpenClaw + Ollama + Docker + monitoring | Bob only — the conductor |
| `llm_worker` | Ollama only | Dedicated inference node |
| `browser_node` | Chrome + HARPA only | D-Tools Cloud automation |
| `full_worker` | Ollama + Docker + HARPA | General-purpose worker (recommended for new nodes) |

---

## How Bob Discovers and Manages Workers

### Discovery
1. `nodes_registry.json` is the ground truth for what nodes exist
2. `node_health_monitor.py` polls each node's health endpoints every N seconds
3. Heartbeat pings from each node arrive at `http://bob:8765/api/heartbeat` every 60 seconds
4. A node is considered `offline` if heartbeat has not been received in 3 minutes OR ping fails

### Routing
1. OpenClaw reads `openclaw_workers.json` on startup (and on SIGHUP for hot reload)
2. Each incoming task is tagged with a type (classify, summarize, reason, browser, etc.)
3. `routing_rules` in `openclaw_workers.json` select the appropriate worker pool
4. Worker selection within a pool uses **priority** (higher = preferred) and **availability** (max_concurrent)
5. If the primary worker is busy or offline, OpenClaw falls back per the rule's `fallback` field
6. Cloud API (`cloud_api` worker) is always the last fallback

### Health checks
```bash
# Human-readable dashboard
python3 ~/.symphony/node_health_monitor.py

# JSON for scripting / OpenClaw
python3 ~/.symphony/node_health_monitor.py --json

# Watch mode (refresh every 30s)
python3 ~/.symphony/node_health_monitor.py --watch 30

# Check single node
python3 ~/.symphony/node_health_monitor.py --node maestro

# Alert on failures via webhook
python3 ~/.symphony/node_health_monitor.py --alert --webhook-url https://hooks.slack.com/...
```

### Cron setup on Bob (recommended)
```bash
# Check all nodes every 5 minutes, alert on failures
*/5 * * * * python3 ~/.symphony/node_health_monitor.py --alert >> ~/.symphony/logs/cron_health.log 2>&1
```

---

## Naming Convention (Orchestra Theme)

New nodes follow an orchestral naming convention — each node plays a role in the "symphony" of the AI network:

| Name | Status |
|------|--------|
| Bob | Conductor (HQ) — active |
| Maestro | Senior musician — active (Intel, 64GB) |
| Stagehand | Crew — active (browser-only) |
| Virtuoso | Next recommended addition |
| Soloist | Specialized task node |
| Concerto | Collaborative worker |
| Overture | Gateway/pre-processor |
| Cadence | Batch/scheduled worker |
| Harmony | Load balancer |
| Tempo | Speed/low-latency worker |
| Crescendo | Power node (Mac Studio) |

---

## Apple Silicon vs Intel: What This Means for Routing

All new nodes should be Apple Silicon. Here's why it matters operationally:

| Metric | Intel (Maestro) | M4 Mac Mini (any) | Mac Studio M4 Max |
|--------|----------------|-------------------|-------------------|
| 8B model speed | ~8 tok/s | ~30 tok/s | ~45 tok/s |
| 70B model speed | ~2 tok/s | N/A (needs 64GB) | ~12 tok/s |
| Power draw | ~90W | ~12W | ~35W |
| Metal acceleration | No | Yes | Yes |
| MLX available | No | Yes | Yes |
| Priority in routing | 40 | 80-90 | 95+ |

Maestro is still valuable because of its 64GB RAM (can load 70B models) — but for interactive tasks, Apple Silicon wins on speed. The routing rules in `openclaw_workers.json` reflect this: Apple Silicon workers get priority 80+, Intel gets priority 40.

---

## Future Expansion Path

```
Phase 1 (current)
  Bob + Maestro + Stagehand
  → Covers all task types; limited throughput

Phase 2 (add 1-2 M4 Mac Minis)
  + Virtuoso (M4 Mac Mini 24GB)  — general purpose
  + Soloist  (M4 Mac Mini 24GB)  — overflow / redundancy
  → 3x LLM throughput on Apple Silicon
  → Maestro demoted to batch-only, Intel CPU tasks

Phase 3 (add Mac Studio)
  + Crescendo (Mac Studio M4 Max 64GB)
  → Local 70B model at interactive speeds
  → Near-elimination of GPT-4 API calls for quality tasks

Phase 4 (scale out)
  + Additional Mac Minis as workers (Concerto, Cadence, Tempo...)
  → True parallel agent execution
  → Bob orchestrates 10+ simultaneous LLM tasks without queuing
```

---

## Key Config Files on Bob

After provisioning Bob, these live at:

```
~/.symphony/
├── registry/
│   ├── nodes_registry.json      ← Node registry (ground truth)
│   └── self_registration.json   ← Bob's own registration payload
├── openclaw_workers.json         ← OpenClaw worker config
├── node_health_monitor.py        ← Health monitor script
├── harpa_setup_instructions.txt  ← HARPA manual setup guide
└── logs/
    ├── node_health.log           ← Health monitor output
    ├── heartbeat.log             ← Outgoing heartbeat log (on worker nodes)
    ├── ollama.log                ← Ollama stdout
    └── ollama_error.log          ← Ollama stderr
```
