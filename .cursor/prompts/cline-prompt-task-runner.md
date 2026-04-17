# Cline Autorun — Symphony Task Runner v1 (Bob)

> **Cline:** read this file top to bottom. Operate in **Act mode only**. Restate the goal in one line, then execute without further prompting unless a Guardrail (§6) forces a stop. After each tool use, summarize in ≤3 bullets. Produce the Final Report in §7.
>
> `AUTO_APPROVE = true`. Read `.clinerules`, `CLAUDE.md`, `STATUS_REPORT.md`, and `ops/AGENT_VERIFICATION_PROTOCOL.md` first.

---

## 1. Goal

Build a **zero-touch control plane** so remote agents (Perplexity Computer, future Cline sessions) can drive Bob without Matt ever copy-pasting a command. The plane is:

- I commit a signed task JSON to `ops/work_queue/pending/<stamp>-<task>.json` and push.
- A launchd job on Bob pulls the repo every 2 min, verifies the signature against committed authorized keys, checks the task against an allowlist, executes it with full tee-to-file logging, writes the result to `ops/verification/`, moves the task to `ops/work_queue/completed/`, commits, and pushes.
- I pull and see the result. Matt is never in the loop.

Non-goals for v1: no webhook/API, no multi-host runner (Bert execution happens by Bob SSHing over Tailscale), no web UI. v1 is a bare launchd + git + python + ed25519 signing pipeline.

## 2. Environment

- **Host:** Bob, `/Users/bob/AI-Server`, branch `main`
- **Python:** `/opt/homebrew/bin/python3`
- **Git author override:** `earleystream@gmail.com` / `Perplexity Computer` (same pattern as existing commits)
- **Tailscale:** Bob can reach Bert at `Matt@macbook-m2-pro.tailbcf3fe.ts.net` (pubkey already placed)
- **Off-limits:** `markup-tool`, `client-portal`, `polymarket-bot`, `email-monitor`, `scripts/imessage-server.py`, `integrations/x_intake/transcript_analyst.py`, `docker-compose.yml`

## 3. Architecture

### 3.1 Directory layout

```
ops/work_queue/
  AUTHORIZED_KEYS.txt        # one ed25519 pubkey per line, "name <base64-pubkey>"
  TASK_SCHEMA.md             # human doc + JSON schema
  pending/                   # tasks waiting to run
  completed/                 # tasks executed successfully
  rejected/                  # tasks that failed signature or allowlist checks
  failed/                    # tasks that ran but exited non-zero
```

### 3.2 Task JSON shape

```json
{
  "task_id": "20260417-083000-bert-hostkey-pin",
  "task_type": "ssh_and_run",
  "created_by": "perplexity-computer",
  "created_at": "2026-04-17T08:30:00-06:00",
  "payload": {
    "host": "Matt@macbook-m2-pro.tailbcf3fe.ts.net",
    "script_name": "bert-hostkey-pin",
    "script_args": []
  },
  "signature": "<base64 ed25519 sig over canonical JSON of task without signature field>"
}
```

### 3.3 Signature scheme

- ed25519, via Python `cryptography` package (add to `/opt/homebrew/bin/python3 -m pip install cryptography` in Phase A).
- Canonical JSON: sort keys, no whitespace, UTF-8.
- Signer computes signature over the task JSON with the `signature` field removed.
- `AUTHORIZED_KEYS.txt` format: `<name> <base64 pubkey>` one per line. Task runner loads all pubkeys and tries each until one verifies.
- Bootstrap: phase H generates a keypair for Cline and puts the pubkey in `AUTHORIZED_KEYS.txt`, but the **private key stays on Bob only** (used by Cline to self-sign test tasks). The runbook in `TASK_SCHEMA.md` explains how Matt (or a remote agent) generates their own keypair.

### 3.4 Allowlist

Task types in v1:

| Task type | Payload | What it does |
|---|---|---|
| `git_pull` | `{}` | `git pull origin main` in repo |
| `run_script` | `{"script": "<name>", "args": []}` | Runs a script from `ops/task_runner/scripts/<name>.sh` — each script is a bash file committed to the repo and reviewed by Matt before first use |
| `ssh_and_run` | `{"host": "...", "script_name": "<name>", "script_args": []}` | SSH to a tailnet host and run a named script there (script is scp'd from repo's `ops/task_runner/remote_scripts/<script_name>.sh`) |
| `verify_dump` | `{"name": "<topic>"}` | Runs a named verification shell block (from `ops/task_runner/verifications/<name>.sh`), tees output, commits under `ops/verification/<stamp>-<topic>.txt` |

Anything else is rejected with an entry in `rejected/` and a line in `ops/verification/<stamp>-rejections.txt`.

### 3.5 Run model

- launchd job `com.symphony.task-runner` with `StartInterval=120` (every 2 min), `RunAtLoad=true`, stderr/stdout to `data/task_runner/launchd.{out,err}.log`.
- Single-instance lock via `data/task_runner/.runner.lock`.
- Per-task timeout: 2 hours. On timeout, task moves to `failed/` and a kill log goes to `ops/verification/`.
- Every run produces a single commit even if no tasks executed (empty runs commit a `heartbeat.txt` update so we can see the runner is alive — throttled to one heartbeat per 10 min to avoid commit spam).

## 4. Step Plan

### Phase A — deps + dirs

```bash
cd /Users/bob/AI-Server
/opt/homebrew/bin/python3 -m pip install --upgrade --quiet cryptography 2>&1 | tail -5

mkdir -p ops/work_queue/pending ops/work_queue/completed ops/work_queue/rejected ops/work_queue/failed
mkdir -p ops/task_runner/scripts ops/task_runner/remote_scripts ops/task_runner/verifications
mkdir -p data/task_runner
touch ops/work_queue/AUTHORIZED_KEYS.txt
echo "last-heartbeat: never" > data/task_runner/heartbeat.txt
```

Commit: `chore(task-runner): scaffold dirs and deps`

### Phase B — signing helper

Create `scripts/task_signer.py`:

```python
#!/usr/bin/env python3
"""
Task signer / verifier for Symphony Task Runner.

Usage:
    python3 task_signer.py keygen --name <signer-name>
        -> writes private key to ~/.config/symphony/<name>.ed25519.priv (mode 600)
        -> appends pubkey line to ops/work_queue/AUTHORIZED_KEYS.txt

    python3 task_signer.py sign --task <path-to-json> --priv <priv-key-path>
        -> computes signature, writes back into the JSON file's "signature" field

    python3 task_signer.py verify --task <path-to-json>
        -> loads AUTHORIZED_KEYS.txt, tries each pubkey, prints "OK <signer-name>" or exits non-zero
"""
```

Implementation uses `cryptography.hazmat.primitives.asymmetric.ed25519`.

Commit: `feat(task-runner): signing helper (keygen/sign/verify)`

### Phase C — task runner

Create `scripts/task_runner.py`. Main loop (invoked once per launchd tick):

1. Acquire lock. If held, log + exit.
2. `git pull origin main` (via subprocess). If conflicts, log and push a rejection note.
3. List `ops/work_queue/pending/*.json`, sorted.
4. For each task:
   - Load JSON.
   - Verify signature via `task_signer.verify`. Reject → move to `rejected/` with reason log.
   - Validate against allowlist. Reject → same.
   - Dispatch to handler for the task type (see §3.4).
   - Tee all output to `ops/verification/<task_id>-result.txt`.
   - On success: move task to `completed/`.
   - On failure: move task to `failed/` with exit code + tail of stderr.
5. Update `heartbeat.txt` if >10 min since last.
6. `git add` any new files under `ops/verification/`, `ops/work_queue/`, `data/task_runner/heartbeat.txt`; commit with message `ops: task-runner tick <stamp> — <N completed / M failed / K rejected>`; push. If nothing changed, skip the commit.
7. Release lock.

Critical implementation notes:

- **Never trust `payload` fields to contain shell interpolations.** Handlers take the structured payload and build argv lists for subprocess, never `shell=True` on user input.
- For `ssh_and_run`, scp the named script from `ops/task_runner/remote_scripts/<script>.sh` to `/tmp/<task_id>-<script>.sh` on the target host, then `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes <host> "bash /tmp/<task_id>-<script>.sh <args>"`. Use `shlex.quote` on args.
- Host key for any target must be pinned before ssh_and_run tasks execute — the first task for a new host should be a local script that does `ssh-keyscan -t ed25519 <host> >> ~/.ssh/known_hosts`.

Commit: `feat(task-runner): executor with allowlist + signature verification`

### Phase D — launchd plist

Create `~/Library/LaunchAgents/com.symphony.task-runner.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.symphony.task-runner</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/python3</string>
    <string>/Users/bob/AI-Server/scripts/task_runner.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>AI_SERVER_ROOT</key><string>/Users/bob/AI-Server</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>StartInterval</key><integer>120</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/Users/bob/AI-Server/data/task_runner/launchd.out.log</string>
  <key>StandardErrorPath</key><string>/Users/bob/AI-Server/data/task_runner/launchd.err.log</string>
</dict>
</plist>
```

Load with `launchctl load ~/Library/LaunchAgents/com.symphony.task-runner.plist`.

Commit: `feat(task-runner): launchd job — every 120s`

### Phase E — initial scripts for the audio work

Create these remote/local scripts — they are what Perplexity Computer will reference in task payloads:

**`ops/task_runner/remote_scripts/bert-hostkey-pin.sh`** — runs on Bert, idempotently pins Bob's SSH host key both directions:

```bash
#!/bin/bash
set -euo pipefail
BOB_FQDN="bobs-mac-mini.tailbcf3fe.ts.net"
BOB_IP="100.89.1.51"
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/known_hosts && chmod 600 ~/.ssh/known_hosts
for h in "$BOB_FQDN" "$BOB_IP"; do
  if ! ssh-keygen -F "$h" >/dev/null 2>&1; then
    ssh-keyscan -T 5 -t ed25519 "$h" 2>/dev/null >> ~/.ssh/known_hosts
  fi
done
awk '!seen[$1" "$2" "$3]++' ~/.ssh/known_hosts > ~/.ssh/known_hosts.dedup && mv ~/.ssh/known_hosts.dedup ~/.ssh/known_hosts
chmod 600 ~/.ssh/known_hosts
echo "bert known_hosts pinned:"
ssh-keygen -lf ~/.ssh/known_hosts | grep -E "bobs-mac-mini|100\.89\.1\.51" || echo "WARN no entries"
```

**`ops/task_runner/remote_scripts/audio-seed-rsync.sh`** — runs on Bert, rsyncs audio to Bob:

```bash
#!/bin/bash
set -euo pipefail
BOB="bob@bobs-mac-mini.tailbcf3fe.ts.net"
ssh -o BatchMode=yes -o StrictHostKeyChecking=yes "$BOB" "mkdir -p /Users/bob/AI-Server/data/audio_intake/incoming"
rsync -avh --partial --stats \
  "$HOME/Documents/Audio Recordings/RECORD/" \
  "$BOB:/Users/bob/AI-Server/data/audio_intake/incoming/"
rsync -avh --partial --stats \
  "$HOME/Documents/Audio Recordings/MEETING/" \
  "$BOB:/Users/bob/AI-Server/data/audio_intake/incoming/"
LANDED=$(ssh -o BatchMode=yes "$BOB" "ls -1 /Users/bob/AI-Server/data/audio_intake/incoming/ 2>/dev/null | wc -l | tr -d ' '")
echo "files-on-bob: $LANDED"
```

**`ops/task_runner/verifications/audio-pipeline.sh`** — runs on Bob, same as the existing verification dump but now called by the runner.

**`ops/task_runner/scripts/approve-router.sh`** — runs on Bob, touches the router approval flag.

Commit: `feat(task-runner): initial scripts for audio pipeline automation`

### Phase F — Schema doc + signer bootstrap

Write `ops/work_queue/TASK_SCHEMA.md` — full human-readable doc with:
- JSON shape example
- Signature flow explained
- How to generate a keypair (`task_signer.py keygen --name <your-name>`)
- How to enroll a new agent (commit the pubkey line to `AUTHORIZED_KEYS.txt` via a human review PR)
- Allowlist catalog

Generate an initial Cline keypair:

```bash
/opt/homebrew/bin/python3 scripts/task_signer.py keygen --name cline-bob
```

Commit: `docs(task-runner): schema + allowlist docs + cline-bob key enrolled`

### Phase G — Enroll "perplexity-computer" key via a placeholder

Add a placeholder line to `AUTHORIZED_KEYS.txt`:

```
# perplexity-computer <PUBKEY WILL BE PROVIDED BY AGENT AT SESSION START — replace this line with the real pubkey>
```

Document in `TASK_SCHEMA.md` that remote agents generate their own keypair at session start and commit only the pubkey (never the private key). The agent's private key lives only in its working session; losing it is fine — a new keypair can always be enrolled.

Commit: `chore(task-runner): perplexity-computer key placeholder`

### Phase H — Smoke test

Generate a test task signed with `cline-bob`:

```bash
cat > /tmp/test-task.json <<'JSON'
{
  "task_id": "<stamp>-smoke-git-pull",
  "task_type": "git_pull",
  "created_by": "cline-bob",
  "created_at": "<iso>",
  "payload": {}
}
JSON
/opt/homebrew/bin/python3 scripts/task_signer.py sign --task /tmp/test-task.json --priv ~/.config/symphony/cline-bob.ed25519.priv
mv /tmp/test-task.json ops/work_queue/pending/
git add . && git commit -m "test: smoke task" && git push

launchctl start com.symphony.task-runner
sleep 10
ls ops/work_queue/completed/
cat ops/verification/*smoke*.txt | tail -20
```

Don't commit the smoke test task — delete `completed/*smoke*` before the final commit. Keep the verification output (it proves the runner works).

### Phase I — Verification block (for the final report)

The block you produce for Matt at the end of your final report goes through the **task runner itself** (meta!), so Matt doesn't paste it. Instead, commit a signed `verify_dump` task to `ops/work_queue/pending/` with `{"name": "task-runner"}`. The next runner tick will execute `ops/task_runner/verifications/task-runner.sh` (which you also create — it dumps runner status, recent commits, dir listings, launchd status) and push the result. Tell Matt to simply wait 2 min and `git pull` to see it, or tell Perplexity Computer to pull.

---

## 5. Acceptance Criteria

- [ ] `cryptography` installed for `/opt/homebrew/bin/python3`
- [ ] All dirs under `ops/work_queue/` and `ops/task_runner/` exist and are committed
- [ ] `scripts/task_signer.py` works: keygen, sign, verify all succeed
- [ ] `scripts/task_runner.py` runs cleanly with an empty queue (writes heartbeat, commits, pushes)
- [ ] launchd job loaded and visible in `launchctl list | grep task-runner`
- [ ] Smoke test task (`git_pull`) completes end-to-end — appears in `completed/`, result in `ops/verification/`
- [ ] Rejected task test: submit an unsigned task, confirm it lands in `rejected/` with reason
- [ ] Allowlist test: submit a task with unknown `task_type`, confirm rejected
- [ ] All six task scripts under `ops/task_runner/{remote_scripts,verifications,scripts}/` exist and are executable
- [ ] `AUTHORIZED_KEYS.txt` has `cline-bob` pubkey + placeholder for `perplexity-computer`
- [ ] `TASK_SCHEMA.md` is complete and accurate
- [ ] No changes to off-limits services (git log confirms)

## 6. Guardrails

- **DO NOT** expose the runner over HTTP/network. It's 100% git-pull driven.
- **DO NOT** allow `run_script` or `ssh_and_run` to take arbitrary shell strings. Only named scripts committed to the repo.
- **DO NOT** commit any private key. Private keys go to `~/.config/symphony/` with mode 600, and that path is in `.gitignore`.
- **DO NOT** auto-execute anything in `ops/work_queue/pending/` without signature verification — the verifier is the only path in.
- **DO NOT** use `#` inline comments in any bash block you produce for Matt (zsh-hostile per `.clinerules`).
- **DO NOT** touch the off-limits services or the meeting/soundscape workers — those are driven by the runner, not modified by it.

## 7. Final Report Format

```
## Task Runner v1 — Final Report

### Commits
- <hash> <subject>
- ...

### Files created
- scripts/task_runner.py (<lines>)
- scripts/task_signer.py (<lines>)
- ops/work_queue/{pending,completed,rejected,failed}/
- ops/task_runner/{scripts,remote_scripts,verifications}/
- ~/Library/LaunchAgents/com.symphony.task-runner.plist

### Smoke test result
- Task submitted: <task_id>
- Completed at: <timestamp>
- Verification file: ops/verification/<name>.txt
- Paste of first 20 lines: ...

### Authorized keys
- cline-bob: <base64 pubkey>
- perplexity-computer: PLACEHOLDER (awaiting pubkey from remote agent)

### launchd status
- Label: com.symphony.task-runner
- Loaded: yes
- Last run: <timestamp>

### Queued verify_dump task for Perplexity Computer
- Task id: <id>
- Expected completion: within 2 min of next launchd tick
- Result will appear at: ops/verification/<id>-result.txt

### Next step for Perplexity Computer
Pull the repo after the next runner tick and read the queued verify_dump result. Then generate your keypair, commit the pubkey to AUTHORIZED_KEYS.txt (replace the placeholder line), and start queuing real tasks.
```

AUTO_APPROVE: true
