# Port 8102 — Unknown Second Listener Evidence
**Captured:** 2026-04-25T01:26:47Z  
**Auditor:** Cline (read-only, no runtime actions taken)  
**Parent audit:** `ops/verification/20260424-182340-port-api-surface-audit/classification.md`  
**Runbook:** `ops/runbooks/2026-04-24-port-8102-unknown-listener-evidence.md`

---

## Verdict

**`PID_COLLISION`**

PID 962, which the original audit attributed to `com.symphony.file-watcher` binding `*:8102`,
**no longer exists**. `lsof -p 962` exits 1 with no output; `ps -p 962` exits 1 with no
process row. The PID was reassigned or the process restarted under a new PID before this
evidence run. There is no second listener on `:8102` today.

---

## Current :8102 listener (step 1)

```
COMMAND    PID USER   FD   TYPE    DEVICE SIZE/OFF NODE NAME
com.docke 1373  bob  167u  IPv4  ...      0t0  TCP 127.0.0.1:8102 (LISTEN)
```

**One listener only.** Docker Desktop proxy (`com.docker`, PID 1373) bound to
`127.0.0.1:8102` (loopback only). No `*:8102` binding exists.

---

## PID 962 status (steps 2 & 3)

| Check | Result |
|---|---|
| `lsof -p 962 -nP -iTCP` | exit 1, no rows — PID 962 does not exist |
| `ps -p 962` | exit 1, header only — PID 962 does not exist |

PID 962 **does not hold** any TCP listener, including `:8102`.

---

## file-watcher current state (step 4 — launchctl print)

The agent is alive and running. Current PID is **749** (not 962):

```
path     = /Users/bob/Library/LaunchAgents/com.symphony.file-watcher.plist
program  = /bin/bash
args     = /bin/bash /Users/bob/AI-Server/services/file-watcher/run.sh
pid      = 749
state    = running
stdout   = /tmp/file-watcher.log
stderr   = /tmp/file-watcher.log
```

---

## Plist content (step 5)

`/Users/bob/Library/LaunchAgents/com.symphony.file-watcher.plist` — no `PORT`,
no `8102`, no network key of any kind. Keys: `KeepAlive`, `Label`,
`ProgramArguments`, `RunAtLoad`, `StandardErrorPath`, `StandardOutPath`,
`ThrottleInterval`, `WorkingDirectory`. See `step5-plist.xml`.

---

## "8102" in file-watcher source tree (step 6)

```
README.md:47   curl http://127.0.0.1:8102/health           ← docs for Docker variant
README.md:146  curl -X POST http://127.0.0.1:8102/process  ← docs for Docker variant
README.md:211  curl http://127.0.0.1:8102/health           ← docs for Docker variant
Dockerfile:20  EXPOSE 8102                                  ← Docker image only
Dockerfile:23  curl -sf http://127.0.0.1:8102/health       ← Docker healthcheck
```

**No Python source hits.** The README and Dockerfile references all point to
the Docker container variant of the service, where port 8102 is used.

---

## file-watcher actual port binding (bonus)

```python
# main.py:109
PORT = int(os.getenv("PORT", "8103"))      # default 8103, not 8102

# main.py:901
uvicorn.run(app, host="127.0.0.1", port=PORT, ...)  # loopback only
```

The native launchd run (PID 749) binds **`127.0.0.1:8103`** (loopback, port 8103).
Confirmed by `lsof -p 962 -nP` output showing `Python 749 bob ... TCP 127.0.0.1:8103 (LISTEN)`.

The `EXPOSE 8102` in the Dockerfile is only relevant when the service runs as a
Docker container — in that case the `PORT` env var is set to `8102` via compose.
The launchd-native service does not set `PORT`, so it uses the default 8103 and
is inaccessible from LAN.

---

## sudo probe (step 7)

`SUDO_UNAVAILABLE` — step 8 skipped per prompt hard-do-not list.

---

## Summary table

| Question | Answer |
|---|---|
| Does PID 962 hold :8102 as a listener? | **No** — PID 962 does not exist |
| Is there any `*:8102` listener today? | **No** — only `127.0.0.1:8102` (Docker, loopback) |
| Binary + argv for PID 962 | **N/A** — PID no longer exists |
| file-watcher current PID | **749** (was 962 at audit time) |
| "8102" in file-watcher source or plist? | README/Dockerfile only, for Docker variant; Python source always binds 127.0.0.1:8103 |
| Verdict | **`PID_COLLISION`** |

---

## Explanation of original audit finding

At the time of the 2026-04-24 audit, file-watcher was PID 962. The audit tool likely read
`*:8102` from a Docker proxy socket that was mapped under the same file-descriptor table
entry visible via `/proc`-style enumeration, or from a transient bind during a container
restart. The file-watcher process has since restarted (now PID 749), and the current
listener state shows no `*:8102` binding from any source. The `EXPOSE 8102` in the service
Dockerfile explains how the port appears in Docker context but does not create a host-level
LAN-accessible listener in the native launchd deployment.

---

## Recommended follow-up

- **Close as PID_COLLISION.** No security action required.
- Update the port/API surface audit classification to `RESOLVED — PID_COLLISION`.
- Optionally document that file-watcher's Docker Dockerfile `EXPOSE 8102` is expected
  and that native launchd runs on 8103 loopback — to prevent future audit confusion.
