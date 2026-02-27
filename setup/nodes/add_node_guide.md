# Adding a New Node to the Symphony AI Network

## Overview

The Symphony AI network is designed to grow incrementally. Each new node you add increases total LLM throughput, enables parallel task execution, and adds redundancy. This guide walks you through the complete process from hardware selection to a running node.

---

## 1. Hardware Recommendations

### Mac Mini M4 — Recommended Default Worker

The M4 Mac Mini is the standard worker node for Symphony. It's compact, silent, power-efficient (~10-15W idle), and delivers exceptional LLM inference throughput via Apple Metal GPU acceleration.

| Config | RAM | Best For | Approx Price |
|--------|-----|----------|--------------|
| Mac Mini M4 | 16GB | Classification, routing, embedding | ~$599 |
| Mac Mini M4 | 24GB | General-purpose LLM worker (recommended minimum) | ~$799 |
| Mac Mini M4 Pro | 24GB | Faster inference + ProRes media tasks | ~$1,199 |
| Mac Mini M4 Pro | 48GB | Heavy reasoning, code generation | ~$1,399 |
| Mac Mini M4 Max | 64GB | Near-cloud quality inference | ~$1,999+ |

### Mac Studio — Heavy Workload Nodes

Reserve Mac Studios for nodes that need to run multiple large models simultaneously, or when you want near-GPT-4 quality inference locally without API costs.

| Config | RAM | Best For |
|--------|-----|----------|
| Mac Studio M4 Max | 64GB | 70B models, parallel 13B+8B |
| Mac Studio M4 Max | 96GB | Multiple simultaneous large models |
| Mac Studio M4 Ultra | 128GB | Near-complete local AI stack |
| Mac Studio M4 Ultra | 192GB | Full enterprise local LLM cluster |

### What to Avoid for New Nodes
- **Intel iMacs**: No Metal ML acceleration. CPU-only inference is 10-30x slower for the same model size. Only Maestro (existing 64GB iMac) is worthwhile due to its large RAM.
- **M1/M2**: Still work great, but M4 is only slightly more expensive and significantly faster. Buy M4+ for new additions.
- **8GB RAM**: Insufficient for any LLM work. Minimum 16GB for an llm_worker node.

---

## 2. What Each RAM Tier Enables

RAM is the most important spec for local LLM inference. On Apple Silicon, all memory is unified (CPU + GPU share the same pool), so all RAM is available for model weights.

### 16GB — Entry Worker
- **Model range**: 7B–13B parameters
- **Sweet spot**: `llama3.2:3b` (~35 tok/s), `llama3.1:8b` (~20 tok/s)
- **Best use cases**: Task classification, intent routing, embedding generation, short summarization
- **Avoid**: Models over 13B — they require GPU offload to slow swap
- **Example assignment**: Lightweight routing node that pre-classifies tasks before sending to heavier workers

### 24GB — General Purpose Worker ✓ Recommended Minimum
- **Model range**: Up to 20B parameters
- **Sweet spot**: `llama3.1:8b` + `mistral:7b` simultaneously, or `codestral:22b` alone
- **Best use cases**: General task handling, code generation, summarization, Q&A
- **Can run**: Two 8B models in parallel for true concurrent inference
- **Example assignment**: `llm_worker` or `full_worker` role, high-priority routing

### 32GB — Strong Reasoning
- **Model range**: Up to 30B parameters
- **Sweet spot**: `llama3.1:8b` + `codestral:22b`, or `mistral-nemo:12b` + `llama3.1:8b`
- **Best use cases**: Complex reasoning, multi-step analysis, technical documentation
- **Can run**: Two medium models simultaneously, or one 30B model
- **Token speed**: ~15-25 tok/s on 8B, ~8-12 tok/s on 20B

### 64GB — Near-GPT-4 Quality Locally
- **Model range**: Up to 70B parameters (Q4_K_M quantization)
- **Sweet spot**: `llama3.1:70b` (Q4_K_M) — excellent quality, reasonable speed
- **Best use cases**: Complex reasoning, long-form writing, nuanced analysis, replacing expensive API calls
- **Token speed**: ~8-15 tok/s on 70B (Q4_K_M) — fast enough for real-time conversation
- **Real-world comparison**: Llama 3.1 70B approaches GPT-4 on many benchmarks
- **Example assignment**: High-priority complex reasoning worker, reduces OpenAI API spend significantly

### 96GB — Mac Studio Territory
- **Model range**: 70B + 8B simultaneously
- **Best use cases**: Parallel task handling — route complex tasks to 70B, simple tasks to 8B concurrently
- **Run simultaneously**: `llama3.1:70b` + `llama3.2:3b` loaded at once, zero cold-start latency

### 128–192GB — Full Cluster on One Machine
- **Model range**: Multiple 70B models, or 70B + 30B + 8B simultaneously
- **Best use cases**: Replacing a small cluster with a single powerful machine
- **192GB Ultra**: Can run a full agent stack — planner (70B) + executor (30B) + router (8B) all local, all fast

---

## 3. Resetting a Used Mac

Before provisioning a new-to-you Mac, perform a full factory reset to start clean. This ensures no previous configurations, software conflicts, or stale SSH keys interfere with the Symphony setup.

**See `imac_reset_guide.md` for detailed instructions.** Quick summary:

1. **macOS 13 (Ventura) or later**: System Settings → General → Transfer or Reset → Erase All Content and Settings
2. **macOS 12 (Monterey) or earlier**: Restart into Recovery Mode (hold Cmd+R), use Disk Utility to erase the main drive, then reinstall macOS from Recovery
3. Complete the initial macOS setup (create a local admin account — do NOT use an Apple ID on worker nodes for simplicity)
4. Ensure the Mac is on the Symphony LAN and can ping Bob

---

## 4. Run provision_node.sh

`provision_node.sh` automates the entire software installation and configuration process.

### Prerequisites
- The new Mac is on the same LAN as Bob
- You know Bob's local IP address (run `ipconfig getifaddr en0` on Bob)
- The Mac has internet access (for Homebrew, Ollama, model downloads)
- You have SSH or physical access to the new Mac

### Step-by-Step

**Step 4a: Copy provision_node.sh to the new Mac**
```bash
# From Bob, copy the scripts directory to the new node
scp -r ~/path/to/setup/nodes/ newnode.local:~/symphony_setup/

# OR: Simply SSH in and download directly
ssh newnode.local
curl -fsSL https://raw.githubusercontent.com/your-org/AI-Server/main/setup/nodes/provision_node.sh -o provision_node.sh
```

**Step 4b: Make it executable and run it**
```bash
chmod +x provision_node.sh

# For a new M4 Mac Mini general-purpose worker:
./provision_node.sh \
  --hostname virtuoso \
  --role full_worker \
  --bob-ip 192.168.1.10

# For a large Mac Studio (70B-capable):
./provision_node.sh \
  --hostname crescendo \
  --role full_worker \
  --bob-ip 192.168.1.10

# For an Intel iMac repurposed as HARPA-only:
./provision_node.sh \
  --hostname stagehand \
  --role browser_node \
  --bob-ip 192.168.1.10
```

**Step 4c: Watch the output**

The script will:
1. Set the Mac's hostname (ComputerName, HostName, LocalHostName)
2. Enable SSH for remote management
3. Install Homebrew
4. Install role-appropriate software (Ollama, Docker, Chrome, etc.)
5. Configure Ollama to listen on `0.0.0.0:11434` for remote access
6. Pull base LLM models (this is the slow part — 7B model ~4GB, 70B model ~40GB)
7. Create launchd plists for auto-start on boot
8. Set up heartbeat cron to Bob
9. Attempt to register with Bob's registry API

**Step 4d: Complete HARPA setup manually (if applicable)**

HARPA AI is a Chrome extension and cannot be installed via CLI. If the node is a `browser_node` or `full_worker`, open Chrome on that Mac and follow the HARPA setup guide saved at `~/.symphony/harpa_setup_instructions.txt`.

---

## 5. Verify from Bob

Once provision_node.sh completes, verify the new node is working from Bob.

```bash
# 1. Check if the new node appears in health monitor
python3 ~/.symphony/node_health_monitor.py

# 2. Test SSH access (passwordless, using Bob's key)
ssh virtuoso.local "hostname && ollama list"

# 3. Test Ollama directly (replace 192.168.1.X with the new node's IP)
curl http://192.168.1.X:11434/api/tags | python3 -m json.tool

# 4. Run a quick inference test
curl http://192.168.1.X:11434/api/generate \
  -d '{"model": "llama3.2:3b", "prompt": "Hello from Bob. Respond in one sentence.", "stream": false}'

# 5. Update nodes_registry.json with the new node's real IP
# Edit ~/.symphony/registry/nodes_registry.json on Bob
```

---

## 6. Assign Roles in OpenClaw Config

Once the node is verified, add it to `openclaw_workers.json` so OpenClaw knows to route tasks to it.

```bash
# Edit the workers config on Bob
nano ~/.symphony/openclaw_workers.json
```

Add a new entry following the template in `openclaw_workers.json`. Key fields:
- **priority**: Higher number = preferred for routing. Apple Silicon nodes should be `90+`.
- **max_concurrent**: Number of simultaneous requests. 1-2 for heavy models, 3-4 for small models.
- **models_available**: Match what you actually pulled on that node.

After updating `openclaw_workers.json`, reload OpenClaw's worker config (exact command depends on your OpenClaw version — typically a `SIGHUP` or admin API endpoint).

---

## 7. Orchestra Naming Convention

Nodes are named after orchestral roles, reflecting their position in the Symphony AI network. When a node goes offline, it's "resting." When the cluster is busy, it's "performing."

| Name | Suggested Role | Notes |
|------|---------------|-------|
| **Bob** | HQ / Conductor | The conductor — orchestrates everything |
| **Maestro** | Senior LLM Worker | 64GB Intel iMac, existing |
| **Stagehand** | Browser Automation | 8GB Intel iMac, existing |
| **Virtuoso** | High-Performance Worker | Suggested next addition (M4 Mac Mini 24GB+) |
| **Soloist** | Specialized Worker | A node dedicated to a specific model/task type |
| **Concerto** | Collaborative Worker | Works alongside other nodes on split tasks |
| **Overture** | Gateway / Pre-processor | If you add an edge node for request intake |
| **Cadence** | Rhythm Worker | Handles scheduled/batch processing tasks |
| **Harmony** | Load Balancer | If you add a dedicated routing layer |
| **Tempo** | Speed Worker | Fast small-model node for low-latency tasks |
| **Crescendo** | Power Worker | The most powerful node — Mac Studio Ultra |

**Naming rules:**
- Use all lowercase for hostnames (e.g., `virtuoso`, not `Virtuoso`)
- Display names capitalize the first letter
- Don't reuse names from decommissioned nodes for 6 months (to avoid SSH key confusion)
- Register the new name in `nodes_registry.json` before provisioning

---

## 8. Troubleshooting

### Node doesn't appear in health monitor
1. Check the IP in `nodes_registry.json` matches the node's actual IP
2. Verify the node can be pinged: `ping virtuoso.local`
3. Check Ollama is listening: `ssh virtuoso.local "curl localhost:11434/api/tags"`
4. Confirm OLLAMA_HOST=0.0.0.0: `ssh virtuoso.local "cat ~/.ollama/ollama.env"`

### Ollama not listening externally
```bash
# SSH to the node and check the launchd plist loaded correctly
ssh virtuoso.local "launchctl list | grep ollama"
# View Ollama logs
ssh virtuoso.local "tail -50 ~/.symphony/logs/ollama.log"
# Manually restart
ssh virtuoso.local "brew services restart ollama"
```

### Model pulls failing
```bash
# Low disk space is a common culprit
ssh virtuoso.local "df -h"
# Check Ollama storage location (default: ~/.ollama/models)
ssh virtuoso.local "du -sh ~/.ollama/models"
# Pull manually
ssh virtuoso.local "ollama pull llama3.1:8b"
```

### Heartbeat not reaching Bob
```bash
# Check cron is running
ssh virtuoso.local "crontab -l"
# View heartbeat log
ssh virtuoso.local "tail -20 ~/.symphony/logs/heartbeat.log"
# Test manually
ssh virtuoso.local "bash ~/.symphony/heartbeat.sh"
```
