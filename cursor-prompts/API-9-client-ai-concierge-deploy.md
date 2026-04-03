# API-9: Client AI Concierge — Deployable Product Package

## The Vision

Every Symphony client gets a private AI appliance — a Mac Mini running a local LLM trained on their specific home. It knows their lighting scenes, their network passwords, their speaker zones, their Control4 remotes. It runs offline, never sends data to the cloud, and answers questions like "What speakers are in my living room?" in under 2 seconds. This is a product Symphony sells. The code exists for onboarding, the concierge server, and knowledge ingestion. Wire it into a deployable package.

Read the existing code first.

## Context Files to Read First

- `client_ai/v2/concierge_server.py`
- `client_ai/v2/knowledge_ingestion.py`
- `client_ai/v2/client_onboarding.py`
- `client_ai/client_knowledge_builder.py`
- `client_ai/update_pipeline.py`
- `client_ai/docker-compose.yml`
- `client_ai/client_registry.json`
- `client_ai/provision_client_node.sh`

## Prompt

The concierge code exists but is not wired together. Build the deployable product package:

### 1. Understand the Client Data Model

Read `client_registry.json` carefully — understand:
- How clients are identified (client_id, name, address)
- What project data fields exist (rooms, devices, scenes, network config)
- How the AI's name and personality are configured per client
- What D-Tools fields map to what knowledge base entries

Every subsequent step must respect this schema. Do not invent new fields; add to the registry schema only if genuinely required.

### 2. Wire Knowledge Ingestion (`client_ai/v2/knowledge_ingestion.py`)

`knowledge_ingestion.py` must pull from two sources and build a ChromaDB vector store:

**Source A: D-Tools project data (Auto-26 system shell)**
```python
# Pull structured project data: rooms, devices, scenes, network topology
# Each device becomes a knowledge chunk: name, location, function, control method
# Each scene becomes a chunk: name, rooms, devices, trigger method
# Network topology: WiFi SSID/passwords, device IPs, VLAN assignments
ingestor.ingest_dtools_export(project_json_path, client_id)
```

**Source B: Symphony knowledge base**
```python
# Pull from knowledge/hardware/*.json and knowledge/products/*.md
# Device manuals → troubleshooting steps for that client's specific devices
# Only ingest docs for devices actually in this client's project
ingestor.ingest_device_manuals(device_sku_list, client_id)
```

ChromaDB collection name: `client_{client_id}` — one collection per client, isolated.
Chunk size: 512 tokens with 64-token overlap.
Embedding model: `nomic-embed-text` via Ollama (already in the stack).

### 3. Wire Client Onboarding (`client_ai/v2/client_onboarding.py`)

Onboarding is a single CLI command that provisions a new client from scratch:

```bash
python3 client_onboarding.py \
  --client-id C0042 \
  --name "Smith Residence" \
  --export /path/to/dtools_export.json \
  --ai-name "Aria"
```

Onboarding steps (in order):
1. Validate the D-Tools export — required fields present, no empty room lists
2. Create entry in `client_registry.json` with all client metadata
3. Run `knowledge_ingestion.ingest_dtools_export()` — build primary knowledge base
4. Run `knowledge_ingestion.ingest_device_manuals()` — add device-specific troubleshooting
5. Generate client system prompt: AI name, house name, room list, personality note
6. Write `data/clients/{client_id}/config.json` — all concierge settings
7. Start (or restart) the concierge server with the new client loaded
8. Run a self-test: ask "What rooms are in this home?" and verify an answer is returned
9. Print the access URL

The onboarding must be idempotent — running it twice on the same client_id updates rather than duplicates.

### 4. Wire Concierge Server (`client_ai/v2/concierge_server.py`)

Fix and test the FastAPI server:

**Endpoints:**
```
POST /chat              — REST chat (JSON in, JSON out)
WebSocket /ws/chat      — streaming chat (for the web UI)
GET  /api/status        — model status, knowledge base size, uptime, client_id
GET  /health            — simple health check for Docker
```

**RAG pipeline per request:**
1. Embed the user's query using `nomic-embed-text`
2. Query ChromaDB: retrieve top 5 most relevant chunks from `client_{client_id}` collection
3. Build augmented prompt: system prompt + retrieved context + conversation history + user query
4. Send to Ollama (`llama3.1:8b`) with streaming enabled
5. Stream tokens back to the client via WebSocket

**Conversation memory:**
- Keep last 10 message pairs in session (in-memory dict keyed by session_id)
- On WebSocket connect: client sends `{"session_id": "abc123"}` or server assigns one
- Store sessions in SQLite: `data/clients/{client_id}/sessions.db`

**The system prompt must include:**
- AI name and personality ("You are Aria, the smart home assistant for the Smith Residence")
- Full room list
- List of all devices by room
- Common phrases and nicknames from the client's project (if available)
- Always answer in plain English, never mention Control4 or technical protocols unless asked

### 5. Test with Topletz Data

Use the Topletz project as the first test:

```bash
# Onboard Topletz
python3 client_onboarding.py \
  --client-id topletz \
  --name "Topletz Residence" \
  --export data/topletz_dtools_export.json \
  --ai-name "Symphony"

# Test question 1: should answer from the device inventory
curl -s -X POST http://localhost:8099/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What speakers are in my living room?", "session_id": "test1"}'

# Test question 2: should answer from the network config
curl -s -X POST http://localhost:8099/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is my WiFi password?", "session_id": "test1"}'

# Verify both answers contain real data from the Topletz project, not hallucinations
```

### 6. Docker Stack (`client_ai/docker-compose.yml`)

Verify the docker-compose is self-contained and starts cleanly with `docker compose up -d`:

```yaml
services:
  ollama:
    image: ollama/ollama
    volumes:
      - ollama_data:/root/.ollama
    # Pulls llama3.1:8b and nomic-embed-text on first start via entrypoint script

  chromadb:
    image: chromadb/chroma
    volumes:
      - chroma_data:/chroma/chroma

  concierge:
    build: ./v2
    ports:
      - "8099:8099"
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - CHROMA_HOST=chromadb
      - CLIENT_ID=${CLIENT_ID}
    depends_on:
      - ollama
      - chromadb
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8099/health"]

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./web_ui:/usr/share/nginx/html:ro
```

If any service in the existing `docker-compose.yml` conflicts with this layout, fix it. The stack must start from a cold machine with a single command.

### 7. Provision Script (`client_ai/provision_client_node.sh`)

Verify `provision_client_node.sh` works on a fresh Mac Mini (macOS 14+):
- Installs Docker Desktop if not present (Homebrew)
- Creates `.env` file with required vars (prompts for CLIENT_ID, AI name)
- Pulls Docker images
- Runs `docker compose up -d`
- Runs health checks on all services
- Prints the access URL (`http://localhost` for web UI, `http://localhost:8099` for API)

The script must be runnable by Matt on a client site with no prior setup — just paste one command.

### 8. Update Pipeline (`client_ai/update_pipeline.py`)

Verify the update pipeline re-ingests knowledge when the project changes:

```bash
# Triggered when D-Tools export changes or Symphony pushes an update
python3 update_pipeline.py --client-id topletz --source dtools

# Must: re-run ingestion, update ChromaDB collection (upsert, don't delete and recreate)
# Must NOT: restart the concierge server mid-conversation (use graceful reload)
```

Use standard logging. All log messages prefixed with `[client-concierge]`.
