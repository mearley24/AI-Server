# Symphony Concierge — Client AI Appliance

> A private, on-premise AI assistant that lives in your client's home, knows their exact
> system, and never sends a byte to the cloud.

**Version:** 2.0.0 | **Status:** Production-ready

---

## What Is Symphony Concierge?

Symphony Concierge is a purpose-built AI appliance installed at each client site. It runs
entirely on a Mac Mini (or Raspberry Pi for budget installs) on the home's local network —
no internet dependency, no cloud subscription, no third-party data exposure.

The AI knows the client's exact system: every device, every scene, every automation, every
support contact. It answers questions, guides troubleshooting, and creates service tickets —
all in natural language, 24/7, even when the internet is down.

---

## Architecture Overview

Data flow: Client asks question → Concierge embeds query → ChromaDB retrieves relevant
system docs → Augmented prompt → Ollama generates answer → Streamed back to client.

---

## Directory Structure

```
client_ai/v2/
├── README.md                        ← You are here
├── knowledge_ingestion.py           ← Ingest system docs into ChromaDB vector store
├── client_onboarding.py             ← One-time setup: build knowledge base from D-Tools export
├── concierge_server.py              ← FastAPI server (RAG + Ollama + WebSocket)
├── appliance_setup.sh               ← Full appliance bootstrap (macOS + Docker)
├── docker-compose.concierge.yml     ← Docker Compose stack definition
├── hardware_specs.md                ← Supported hardware: Mac Mini M2/M4, Raspberry Pi 5
├── pricing_model.md                 ← Pricing tiers: Standard / Pro / Enterprise
└── web_ui/
    └── index.html                   ← Client-facing chat UI (dark mode, mobile-first)
```

---

## Quick Start (New Client Install)

### Prerequisites

- Mac Mini M2 Pro or better (recommended) or Raspberry Pi 5 8GB
- macOS 14+ or Ubuntu 24.04 LTS
- Docker Desktop (macOS) or Docker Engine (Linux)
- 500GB SSD (models + knowledge + conversations)
- Local network access

### Step 1: Run the Appliance Setup Script

```bash
bash appliance_setup.sh
```

This script will:
1. Install dependencies (Homebrew, Docker, Python 3.11+)
2. Pull Ollama and the base LLM model (~4.7GB download)
3. Clone this repository to `/opt/symphony/concierge/`
4. Create the `.env` file from prompts
5. Pull all Docker images
6. Start the full container stack
7. Run a health check

### Step 2: Onboard the Client

```bash
python3 client_onboarding.py \
  --client-id C0042 \
  --name "Smith Residence" \
  --export /tmp/client_export.json \
  --ai-name "Aria"
```

### Step 3: Access the Interface

Open a browser on any device on the home network:

```
http://192.168.1.100   (replace with Mac Mini's IP)
```

---

## Components

### `knowledge_ingestion.py`

The RAG knowledge pipeline. Converts system documentation into searchable vector embeddings.

### `client_onboarding.py`

One-time setup that transforms a D-Tools project export into a fully-populated knowledge base.

### `concierge_server.py`

FastAPI server providing the AI interface:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Single-turn chat (returns full response) |
| `/ws/chat` | WebSocket | Streaming chat (token-by-token) |
| `/api/status` | GET | System health + model status |
| `/api/knowledge/query` | POST | Direct knowledge base query |
| `/api/knowledge/ingest` | POST | Add new document |
| `/health` | GET | Docker health check endpoint |

### `web_ui/index.html`

Mobile-first chat interface with dark mode, real-time streaming, and offline support.

### `appliance_setup.sh`

Full bootstrap script for a fresh Mac Mini or Raspberry Pi.

---

## Configuration

### Environment Variables (`.env`)

```bash
CLIENT_ID=C0042
AI_NAME=Aria
BASE_MODEL=llama3.1:8b
MODEL_TAG=llama3.1:8b
CONCIERGE_HOME=/opt/symphony/concierge
```

---

## Privacy & Security

| Concern | How it's handled |
|---------|------------------|
| **Data storage** | All data stays on the local appliance. Nothing leaves the LAN except heartbeat pings. |
| **LLM inference** | 100% local via Ollama. No OpenAI, no Anthropic, no external API. |
| **Conversation history** | Stored locally. Never transmitted. |
| **Heartbeat** | Sends only: client_id, version, service status. No PII. |
| **Network exposure** | Only nginx port 80 is exposed to LAN. |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.0.0 | 2026-02-27 | Full rewrite: Docker stack, ChromaDB RAG, WebSocket streaming, mobile UI |
| 1.5.0 | 2025-11-01 | Added web UI, improved knowledge ingestion |
| 1.0.0 | 2025-07-15 | Initial release: CLI-only, flat-file knowledge base |

---

*Symphony Smart Homes — Client AI Appliance v2.0.0*
