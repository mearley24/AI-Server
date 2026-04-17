# Symphony Task Runner — TASK_SCHEMA

Authoritative reference for signed tasks processed by `scripts/task_runner.py`.

A task is a JSON file committed to `ops/work_queue/pending/`. Every 2 minutes
the launchd-scheduled runner pulls `origin/main`, verifies each pending task's
ed25519 signature against `AUTHORIZED_KEYS.txt`, checks the task type against
an allowlist, executes the matching handler with all output teed into
`ops/verification/<task_id>-result.txt`, moves the task to `completed/` /
`failed/` / `rejected/`, and commits + pushes everything back.

This entire pipeline is git-driven. There is no HTTP endpoint, no webhook,
and no network-exposed daemon: to queue work on Bob you push a file to main.

---

## File layout

```
ops/work_queue/
  AUTHORIZED_KEYS.txt    # one "<name> <base64-ed25519-pubkey>" per line
  TASK_SCHEMA.md         # this file
  pending/               # tasks waiting to run
  completed/             # tasks that ran successfully
  failed/                # tasks that ran but exited non-zero
  rejected/              # bad signature, unknown type, or malformed JSON

ops/task_runner/
  scripts/               # local shell scripts invoked by run_script
  remote_scripts/        # scp'd-and-run shell scripts for ssh_and_run
  verifications/         # verify_dump scripts (produce log dumps)
  com.symphony.task-runner.plist  # reference copy of the launchd plist

ops/verification/        # per-task result logs + rejection notes

data/task_runner/
  heartbeat.txt          # last tick timestamp (committed at most every 10 min)
  .runner.lock           # advisory single-instance lock
  launchd.out.log        # launchd stdout
  launchd.err.log        # launchd stderr
```

---

## Task JSON shape

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
  "signature": "<base64 ed25519 signature of the canonical JSON of the task without this field>"
}
```

Required fields: `task_id`, `task_type`, `created_by`, `created_at`,
`payload`, `signature`. Extra fields are ignored.

### `task_id` naming

Use `<UTC-YYYYMMDD>-<UTC-HHMMSS>-<short-topic>` so filename sort order matches
chronological order. Keep it filesystem-safe (ASCII, dashes, no spaces).

### `created_by`

The signer name. Used only for display/logging; signature verification is
what actually authenticates the task.

---

## Allowlist — task types in v1

| `task_type` | `payload` keys | Behavior |
|---|---|---|
| `git_pull` | `{}` | `git pull --ff-only origin main` in the repo. |
| `run_script` | `{"script": "<name>", "args": [scalar, ...]}` | Executes `ops/task_runner/scripts/<name>.sh` with `args` as positional arguments. Only scalars allowed. |
| `ssh_and_run` | `{"host": "user@host", "script_name": "<name>", "script_args": [scalar, ...]}` | scp's `ops/task_runner/remote_scripts/<name>.sh` to `/tmp/<task_id>-<name>.sh` on `host`, then runs it via `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes`. The script must exist in the repo. `script_args` are `shlex.quote`'d before being embedded in the remote command. |
| `verify_dump` | `{"name": "<topic>", "args": [scalar, ...]}` | Runs `ops/task_runner/verifications/<name>.sh` on Bob, tees output into `ops/verification/<task_id>-result.txt`, commits + pushes. |

Any other `task_type` is **rejected** (moved to `rejected/`, reason written to
`ops/verification/<stamp>-rejections.txt`).

### Security notes

- Payload fields are never interpolated into shell strings. Scripts receive
  positional `bash argv`, not shell expansion of the payload.
- Script names are validated: no `/`, no `..`, no leading `.`, resolved paths
  must stay inside their parent directory.
- `ssh_and_run` uses `BatchMode=yes` and `StrictHostKeyChecking=yes`. Host keys
  must be pinned (e.g. via `ssh-keyscan` in a `run_script`) before the first
  `ssh_and_run` to a new host, or the task will fail loudly. **Never** use
  `StrictHostKeyChecking=no` anywhere — it silently accepts MITM swaps.
- `ssh_and_run` cleans up the remote script after the run (best-effort).

---

## Signature scheme

- **Algorithm:** Ed25519 via the Python `cryptography` package.
- **Canonical JSON:** `json.dumps(task_without_signature, sort_keys=True,
  separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
- **Signature field:** `task["signature"] = base64(sig_bytes)`.
- **Pubkey enrollment:** append a line `<name> <base64-pubkey>` to
  `ops/work_queue/AUTHORIZED_KEYS.txt`. Lines starting with `#` are comments
  (used for placeholders).
- **Verifier:** tries every enrolled pubkey until one validates. Task accepted
  if any key matches; rejected otherwise.

### Private keys

- Stored at `~/.config/symphony/<name>.ed25519.priv` with mode 600.
- Raw base64-encoded Ed25519 seed (32 bytes). Not a PEM / PKCS#8 file.
- Never committed. `~/.config/symphony/` is outside the repo by design.
- Losing a private key is cheap: generate a new one and enroll it. An old
  key can be deactivated by removing its line from `AUTHORIZED_KEYS.txt`.

---

## How to queue a task (for a human or remote agent)

1. Clone/pull this repo.
2. Generate a keypair if you don't already have one:
   ```
   /opt/homebrew/bin/python3 scripts/task_signer.py keygen --name <your-name>
   ```
   This writes `~/.config/symphony/<your-name>.ed25519.priv` and appends a
   line to `AUTHORIZED_KEYS.txt`.
3. Commit and push **only** the new `AUTHORIZED_KEYS.txt` line, never the
   private key. Matt (or another human reviewer) reviews the enrollment
   commit.
4. Build a task JSON file at
   `ops/work_queue/pending/<YYYYMMDD-HHMMSS>-<topic>.json`. Fill in
   `task_id`, `task_type`, `created_by` (your name), `created_at`, and
   `payload`.
5. Sign it in place:
   ```
   /opt/homebrew/bin/python3 scripts/task_signer.py sign \
     --task ops/work_queue/pending/<file>.json \
     --priv ~/.config/symphony/<your-name>.ed25519.priv
   ```
6. `git add ops/work_queue/pending/<file>.json && git commit -m "task:
   <topic>" && git push`.
7. Within ~2 minutes the runner picks it up. Pull and look at
   `ops/verification/<task_id>-result.txt` for the output.

---

## Worked example — queue a `verify_dump` task

```
/opt/homebrew/bin/python3 - <<'PY_DISALLOWED'
# DO NOT DO THIS (heredoc is zsh-hostile per .clinerules). Use a .py helper
# or printf'd one-liners to construct the JSON instead.
PY_DISALLOWED
```

Safe pattern — create the file with a tiny Python script, then sign:

```
python3 scripts/_make_task.py \
  --type verify_dump --name task-runner \
  --out ops/work_queue/pending/20260417-090000-verify-task-runner.json
python3 scripts/task_signer.py sign \
  --task ops/work_queue/pending/20260417-090000-verify-task-runner.json \
  --priv ~/.config/symphony/<your-name>.ed25519.priv
git add ops/work_queue/pending && git commit -m "task: verify task-runner"
git push origin main
```

(`scripts/_make_task.py` is a tiny helper each agent is free to write for
itself; it is not part of the task runner contract.)

---

## Heartbeat, commits, and locks

- Each launchd tick: `git pull`, process pending, maybe update
  `data/task_runner/heartbeat.txt` (at most once per 10 minutes), then
  `git add + commit + push` if there were any changes. Empty ticks with
  nothing to do produce no commit.
- Commit author: `Perplexity Computer <earleystream@gmail.com>`.
- Commit message: `ops: task-runner tick <YYYYMMDD-HHMMSS> — N completed / M
  failed / K rejected` (or `heartbeat` if only the heartbeat changed).
- Two launchd ticks cannot race: an `fcntl` advisory lock at
  `data/task_runner/.runner.lock` means a second tick exits immediately if
  the first is still running.
- Per-task timeout: **2 hours**. A timed-out task moves to `failed/`.

---

## Operational notes

### Deploying the runner

```
cp ops/task_runner/com.symphony.task-runner.plist \
   ~/Library/LaunchAgents/com.symphony.task-runner.plist
launchctl load ~/Library/LaunchAgents/com.symphony.task-runner.plist
launchctl list | grep task-runner
```

Interval is 120 seconds with `RunAtLoad=true`. Stdout/stderr:
`data/task_runner/launchd.{out,err}.log`.

### Inspecting the runner

`ops/task_runner/verifications/task-runner.sh` produces a comprehensive
snapshot (launchd status, heartbeat, queue counts, recent commits). Queue a
`verify_dump` task with `{"name": "task-runner"}` to run it remotely.

### Updating the allowlist

Adding a new `task_type` requires editing `scripts/task_runner.py`:
`ALLOWED_TASK_TYPES` plus a handler function. That's intentional — every new
capability is a reviewed code change, not a data change.

### Adding a new script

Drop a `<name>.sh` into the right directory (`scripts/`, `remote_scripts/`,
or `verifications/`), commit it, and reference it by `name` (no extension)
in a task payload. No code change needed.

---

## Enrolled signers

See `AUTHORIZED_KEYS.txt` — one `<name> <base64-pubkey>` per line. Initial
enrollments:

- `cline-bob` — Cline's local key on Bob. Used to self-sign test tasks
  generated from Cline sessions.
- `perplexity-computer` — placeholder. The real Perplexity Computer agent
  generates its own keypair at session start (via `task_signer.py keygen
  --name perplexity-computer --force`) and commits the new pubkey line,
  replacing the placeholder comment.
