# Ollama Worker Node — 64GB iMac
**Symphony Smart Homes | Bob the Conductor Infrastructure**

This iMac is configured as a dedicated LLM inference worker node, serving local AI requests from Bob the Conductor (Mac Mini M4).

---

## Hardware

| Item | Spec |
|---|---|
| Machine | 2019 iMac (Intel Core i3, 64GB RAM) |
| Role | Ollama LLM worker node |
| Network role | Ollama server at `http://[IMAC_IP]:11434` |
| RAM available for models | ~48–56GB (after OS) |
| CPU | Intel Core i3-8100 (4 cores) — CPU-only inference |
| Inference speed | ~5–15 tokens/sec for 7–8B models |

---

## Models Installed

| Model | RAM (~) | Speed | Use Case |
|---|---|---|---|
| `llama3.2:3b` | ~2GB | fast | Simple tasks, routing |
| `llama3.1:8b` | ~5GB | medium | General purpose |
| `mistral:7b` | ~5GB | medium | Structured output, JSON |
| `bob-classifier` | ~2GB | fast | Document classification |
| `bob-summarizer` | ~5GB | medium | Document summarization |

**Total RAM footprint (all loaded):** ~19GB  
**Available for additional models:** ~30GB+

---

## Architecture

```
[Bob the Conductor]       [64GB iMac Worker]
   Mac Mini M4    ──────── http://[IP]:11434
   OpenClaw                  Ollama server
   Anthropic API             CPU-only inference
   OpenAI API                llama3.2:3b
                             llama3.1:8b
                             mistral:7b
                             bob-classifier
                             bob-summarizer

[8GB iMac]               [64GB iMac Worker]
   HARPA browser  ──────── same Ollama endpoint
   automation              (used for document
                            processing tasks)
```

---

## Setup

Run the setup script on the 64GB iMac:

```bash
# Clone or copy the repo
git clone https://github.com/mearley24/AI-Server.git ~/AI-Server
cd ~/AI-Server/setup/ollama_worker

# Make executable and run
chmod +x setup_ollama_worker.sh
./setup_ollama_worker.sh
```

The script will:
1. Install Homebrew and dependencies
2. Install Ollama
3. Create and start the launchd service (auto-start on boot)
4. Configure the environment from `ollama_worker.env`
5. Pull all required models
6. Build the custom `bob-classifier` and `bob-summarizer` models
7. Run a basic health check

---

## Environment Configuration

See `ollama_worker.env` for all configurable settings:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `0.0.0.0:11434` | Listen address (LAN accessible) |
| `OLLAMA_NUM_PARALLEL` | `1` | Concurrent requests (1 for 4-core CPU) |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Max models in RAM simultaneously |
| `OLLAMA_KEEP_ALIVE` | `5m` | Keep model in RAM after last request |
| `OLLAMA_FLASH_ATTENTION` | `1` | Enable Flash Attention (CPU optimization) |

---

## Diagnostics

Run the full diagnostic suite:
```bash
chmod +x test_ollama_worker.sh
./test_ollama_worker.sh
```

Or run individual checks:
```bash
# Quick health check
curl http://localhost:11434/api/tags

# Test classification
curl -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model": "bob-classifier", "prompt": "Control4 EA-5 Installation Guide", "stream": false}'

# Test summarization
curl -X POST http://localhost:11434/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model": "bob-summarizer", "prompt": "Summarize: Symphony Smart Homes Proposal for Smith Residence. Control4 EA-5, Lutron RadioRA 3, 8 zones Sonos. Total: $42,000.", "stream": false}'

# List loaded models
curl http://localhost:11434/api/ps
```

---

## Ollama Service Management

```bash
# Check service status
launchctl list | grep ollama

# Stop service
launchctl unload ~/Library/LaunchAgents/com.ollama.plist

# Start service
launchctl load ~/Library/LaunchAgents/com.ollama.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.ollama.plist
launchctl load ~/Library/LaunchAgents/com.ollama.plist

# View logs
tail -f ~/Library/Logs/ollama_worker.log
tail -f ~/Library/Logs/ollama_worker_error.log
```

---

## Connecting from Bob (Mac Mini M4)

In Bob's OpenClaw config (`~/.openclaw/openclaw.json`):
```json
"ollama": {
  "enabled": true,
  "base_url": "http://[IMAC_LOCAL_IP]:11434",
  "openai_compatible": true,
  "default_model": "llama3.1:8b",
  "timeout_ms": 120000
}
```

To find the iMac's local IP:
```bash
ipconfig getifaddr en0  # Wi-Fi
ipconfig getifaddr en1  # Ethernet (preferred for stability)
```

Or check **System Preferences → Network → [Interface] → IP Address**.

---

## Performance Notes

- **CPU-only inference** is slower than GPU but fully functional for background tasks
- **llama3.2:3b** (bob-classifier): ~8–12 tokens/sec — fast enough for real-time classification
- **llama3.1:8b** (bob-summarizer): ~3–6 tokens/sec — suitable for batch document processing
- **OLLAMA_NUM_PARALLEL=1**: Only one request at a time — prevents resource contention on 4-core CPU
- **OLLAMA_MAX_LOADED_MODELS=2**: Keeps 2 models in RAM to avoid reload overhead
- **Warm-up**: First request after service start takes longer (model loading). Subsequent requests use cached model.

---

## Updating Models

```bash
# Pull latest version of a model
ollama pull llama3.1:8b
ollama pull llama3.2:3b
ollama pull mistral:7b

# Rebuild custom models after base model update
cd ~/AI-Server/setup/ollama_worker
ollama create bob-classifier -f Modelfile.bob-classifier
ollama create bob-summarizer -f Modelfile.bob-summarizer

# Verify
ollama list
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Ollama not responding | `launchctl load ~/Library/LaunchAgents/com.ollama.plist` |
| Model not found | `ollama pull [model-name]` |
| Slow inference | Normal for CPU-only. Check `OLLAMA_NUM_PARALLEL=1` in env |
| Connection refused from Bob | Check firewall: System Preferences → Security → Firewall → Allow Ollama |
| Out of memory | Reduce `OLLAMA_MAX_LOADED_MODELS` to 1 in env |
| Custom model missing | Rebuild: `ollama create bob-classifier -f Modelfile.bob-classifier` |
| Bob can't reach iMac | Verify IP in `openclaw.json` matches `ipconfig getifaddr en1` |

---

## File Reference

| File | Purpose |
|---|---|
| `setup_ollama_worker.sh` | Full setup script — run once on fresh iMac |
| `ollama_worker.env` | Environment variables loaded by launchd service |
| `test_ollama_worker.sh` | Diagnostic and test suite |
| `Modelfile.bob-classifier` | Custom classifier model definition |
| `Modelfile.bob-summarizer` | Custom summarizer model definition |
| `README.md` | This file |
