# Symphony Setup UI

One-click setup for M2 MacBook Pro (LLM worker) and verification from Bob (Mac Mini HQ).

Maestro (Intel iMac) was retired 2026-04-16. Bob (M4 Mac Mini) is now the sole primary node.

## Run on M2 MacBook Pro (first-time setup)

If the M2 doesn't have the repo yet, copy this folder from Bob:

```bash
scp -r ~/AI-Server/setup/setup_ui m2user@m2.local:~/
```

Then on M2:

```bash
cd ~/setup_ui
python3 server.py
```

Open http://localhost:8888 and click the buttons in order.

## Run on Bob (or when repo exists)

```bash
cd ~/AI-Server/setup/setup_ui
python3 server.py
```

Open http://localhost:8888.

## Buttons

| Button | Run on | What it does |
|--------|--------|--------------|
| 1. Clone AI-Server | M2 | `git clone` into ~/AI-Server |
| 2. Run HARPA setup | M2 | setup_imac_harpa.sh |
| 3. Run Ollama setup | M2 | setup_ollama_worker.sh |
| Verify Ollama | Bob | curl M2:11434 |
| Verify HARPA bridge | Bob | curl M2:9090 |

Set the M2's IP in the input field before running verify steps.

## M2 Ollama Setup (standalone)

For a quick Ollama-only setup on the M2, run directly on the M2:

```bash
bash ~/AI-Server/scripts/setup-ollama-m2.sh
```

Then update `setup/nodes/nodes_registry.json` on Bob with the M2's actual IP address.
