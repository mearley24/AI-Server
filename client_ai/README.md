# Symphony Concierge — Client AI Appliance

Symphony Concierge is a **private, local AI assistant** deployed inside high-end client homes. It runs entirely on a **Mac Mini M4** with no cloud dependencies — all inference is handled by [Ollama](https://ollama.com) running a custom Llama 3 model trained on the client's specific home systems.

Clients interact through a beautiful browser-based chat UI optimised for a dedicated tablet, asking questions like:

> "Why is my music not playing in the master bedroom?"
> "Turn on movie mode in the living room."
> "What's the Wi-Fi password for guests?"

---

## Architecture

```
Client Tablet (browser)
      │  HTTP
      ▼
Nginx (localhost:80)
      │
      ▼
Ollama API (localhost:11434)
      │  Custom Modelfile
      ▼
Llama 3 + client knowledge base
```

No traffic leaves the home network except:
- **Tailscale** — encrypted admin tunnel for Symphony technicians to push model updates.
- **Ollama model pulls** — one-time during initial provisioning.

---

## Files

| File / Folder | Purpose |
|---|---|
| `client_knowledge_builder.py` | Ingest D-Tools CSV → Ollama Modelfile |
| `client_registry.json` | Master registry of all deployed Concierge nodes |
| `client_system_prompt.md` | Base system prompt template |
| `docker-compose.yml` | Ollama + Nginx stack |
| `pricing_model.md` | Hardware + subscription pricing |
| `provision_client_node.sh` | Zero-touch provisioning script |
| `update_pipeline.py` | Remote model update over Tailscale |
| `client_ui/` | Browser chat interface |
| `troubleshooting_templates/` | Per-system guides injected into knowledge base |

---

## Quick Start

### 1. Provision a new node

```bash
# On a fresh Mac Mini M4:
bash provision_client_node.sh --client "The Andersons" --tailscale-key tskey-xxxx
```

### 2. Build the knowledge model

```bash
# Provide D-Tools CSV export:
python3 client_knowledge_builder.py \
  --client "The Andersons" \
  --dtools-csv /path/to/andersons_dtools.csv \
  --templates ./troubleshooting_templates/
```

### 3. Launch the stack

```bash
docker compose up -d
```

### 4. Access the UI

Open `http://localhost` on the client's tablet. The chat interface is ready.

---

## Updating a Deployed Node

```bash
# From the AI Server (over Tailscale):
python3 update_pipeline.py --client "The Andersons" --model-version 2
```

The pipeline checks for active sessions, pushes the new Modelfile, re-creates the Ollama model, and restarts the service — all without physical access.
