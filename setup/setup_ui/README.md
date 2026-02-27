# Symphony Setup UI

One-click setup for Betty (64GB iMac) and verification from Bob (Mac Mini).

## Run on Betty (first-time setup)

If Betty doesn't have the repo yet, copy this folder from Bob:

```bash
scp -r ~/AI-Server/setup/setup_ui betty@maestro.local:~/
```

Then on Betty:

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
| 1. Clone AI-Server | Betty | `git clone` into ~/AI-Server |
| 2. Run HARPA setup | Betty | setup_imac_harpa.sh |
| 3. Run Ollama setup | Betty | setup_ollama_worker.sh |
| Verify Ollama | Bob | curl Betty:11434 |
| Verify HARPA bridge | Bob | curl Betty:9090 |

Set Betty's IP in the input field before running verify steps.
