# Auto-15: Ollama on Maestro — Local LLM Infrastructure

## Context Files to Read First
- setup/ollama_worker/README.md
- setup/nodes/add_node_guide.md
- setup/nodes/imac_reset_guide.md
- AGENTS.md (architecture overview)

## Prompt

Set up Ollama on Maestro (64GB iMac) as a local LLM inference node for Bob's stack:

1. **Setup script** (`setup/ollama_worker/setup_maestro.sh`):
   - Install Ollama on macOS: `curl -fsSL https://ollama.com/install.sh | sh`
   - Pull models: `llama3.1:8b` (general), `codellama:13b` (code tasks), `nomic-embed-text` (embeddings)
   - With 64GB RAM, Maestro can run 13B models comfortably
   - Configure Ollama to listen on all interfaces: `OLLAMA_HOST=0.0.0.0:11434`
   - Create launchd service for auto-start: `setup/launchd/com.symphony.ollama.plist`

2. **Bob → Maestro routing** (`setup/ollama_worker/ollama_router.py`):
   - FastAPI proxy on Bob (port 11435) that routes LLM requests to Maestro
   - Health check Maestro every 30s; if offline, fall back to OpenAI API
   - Load balancing: if request queue > 3, overflow to OpenAI
   - Track usage: tokens processed locally vs via OpenAI API (cost savings metric)

3. **Integration points** — replace OpenAI calls with local Ollama where possible:
   - Email classification (`email-monitor/analyzer.py`): switch from GPT-4o-mini to llama3.1:8b for email triage (saves ~$0.50/day)
   - LLM validator (`polymarket-bot/strategies/llm_validator.py`): use local model for trade validation pre-screening, escalate to GPT-4o only for uncertain cases
   - ClawWork quality control: use local model for first-pass review
   - Knowledge scanner: use local model for fact extraction
   - Keep GPT-4o/Claude for: complex reasoning, proposal generation, client communications

4. **Embeddings**:
   - Use `nomic-embed-text` on Maestro for all vector operations
   - Client AI Concierge (API-9) should use Maestro for embeddings if on the same network
   - ChromaDB can point to Maestro's embedding endpoint

5. **Monitoring**:
   - Maestro health visible in Mission Control dashboard
   - Daily cost savings report: "Local inference saved $X today vs OpenAI pricing"
   - Alert if Maestro goes offline for >10 minutes

Use standard logging.
