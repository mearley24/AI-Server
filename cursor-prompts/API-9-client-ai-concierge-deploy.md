# API-9: Client AI Concierge — First Customer Deployment

## Context Files to Read First
- client_ai/v2/README.md (full architecture)
- client_ai/v2/concierge_server.py
- client_ai/v2/knowledge_ingestion.py
- client_ai/v2/client_onboarding.py
- client_ai/v2/docker-compose.concierge.yml
- client_ai/v2/hardware_specs.md
- client_ai/v2/pricing_model.md
- client_ai/client_knowledge_builder.py
- client_ai/troubleshooting_templates/*.md

## Prompt

Make the Symphony Concierge client AI appliance ready for first deployment:

1. **Onboarding pipeline** (`client_ai/v2/client_onboarding.py` — fix and test):
   - Accept a D-Tools project export (JSON) + room list + device inventory
   - Build ChromaDB vector store from: device manuals, room configs, scene definitions, network topology, troubleshooting guides
   - Generate the client-specific system prompt with their AI's name, their house layout, and their devices
   - Output: fully populated knowledge base ready to serve
   - CLI: `python3 client_onboarding.py --client-id C0042 --name "Smith Residence" --export /path/to/export.json --ai-name "Aria"`

2. **Concierge server** (`client_ai/v2/concierge_server.py` — fix and test):
   - FastAPI server with REST `/chat` and WebSocket `/ws/chat` endpoints
   - RAG pipeline: embed query → ChromaDB retrieval (top 5 chunks) → augmented prompt → Ollama inference → streamed response
   - System prompt includes: client name, AI personality, device list, common troubleshooting steps
   - Conversation memory: last 10 messages in session, stored in SQLite
   - `/api/status` endpoint showing model status, knowledge base size, uptime

3. **Troubleshooting templates** — expand the existing set:
   - Control4: "my remote isn't working", "a room shows offline", "scenes not triggering"
   - Lutron: "lights not responding", "shades stuck", "keypad buttons wrong"
   - Audio: "no sound in [room]", "volume too low", "wrong music source"
   - Network: "internet is slow", "devices offline", "can't connect to WiFi"
   - Each template: symptom → likely cause → step-by-step fix → when to call Symphony

4. **Docker stack** (`client_ai/v2/docker-compose.concierge.yml`):
   - Services: `ollama` (model serving), `chromadb` (vector store), `concierge` (FastAPI app), `nginx` (reverse proxy + static UI)
   - Ollama pulls `llama3.1:8b` on first start
   - Health checks on all services
   - Single command startup: `docker compose -f docker-compose.concierge.yml up -d`

5. **Web UI** (`client_ai/v2/web_ui/index.html`):
   - Clean chat interface, dark mode, mobile-first
   - WebSocket connection for streaming responses
   - Offline detection (show "AI is loading..." when Ollama is cold-starting)
   - Symphony branding: logo, color scheme, "Powered by Symphony Smart Homes"

6. **Appliance setup script** (`client_ai/v2/appliance_setup.sh`):
   - One command to bootstrap a fresh Mac Mini: install Docker, pull images, configure .env, start stack
   - Post-install health check
   - Print access URL

Use standard logging.
