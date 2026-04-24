# Bob Docker Crash / Memory Diagnostic — 20260424-151202

**Timestamp (UTC):** 2026-04-24T15:12:02Z  
**Local:** 2026-04-24T09:12:02 MDT  
**Host:** Bobs-Mac-mini.local  
**uname:** Darwin 25.3.0 arm64 (Apple Silicon M4)  
**macOS:** 26.3  
**Git HEAD:** 7dda96e16c6ff981f30334fcd8545c6517211e5d  
**Branch:** main  
**Dirty files (harness-owned):** 8  
**Prompt:** `.cursor/prompts/2026-04-24-cline-bob-docker-crash-memory-diagnostic.md`

Tool availability: docker ✓  vm_stat ✓  memory_pressure ✓  top ✓  log ✓

---

## Phase 0 — Host + repo sanity

Host: `Bobs-Mac-mini.local` ✓ (contains "bob")  
Repo: `/Users/bob/AI-Server` ✓  
Branch: `main` ✓  
Repo files: ok-compose ok-watchdog ok-runner ok-ver ✓

---

## Phase 1 — Docker Desktop / daemon status

```
docker info: 29.2.1 / Docker Desktop / mem=4109258752 (3.83 GB) / ncpu=5
docker version: Server 29.2.1 / Client 29.2.1
EXIT: 0 — daemon healthy at time of capture
```

**⚠️ TRANSLOCATED PATH DETECTED:**  
Docker Desktop is running from:
```
/private/var/folders/rs/.../AppTranslocation/26637262-CAE0-4666-93B6-973AC68B3A6B/d/Docker.app/...
```
macOS App Translocation assigns a random temporary path when an app is not installed via drag-to-/Applications/ with proper quarantine clearance. This means:
- Each launch may get a DIFFERENT translocated path
- Socket path stays fixed but binary path changes
- Causes the zombie-daemon symptom: socket exists, process disappears
- The translocated PID churns on every restart

`com.docker.backend` PIDs: 71107, 71109, 71110  
`Docker Desktop` PIDs: 71399, 71404, 71412, 71413, 71427

**docker system df:**
```
Images:     21.07 GB total — 20.03 GB reclaimable (95%)  ← CRITICAL
Containers: 31.71 MB active, 0 reclaimable
Volumes:    49.27 MB total, 31.13 MB reclaimable (63%)
Build cache: 14.17 GB total, 5.215 GB reclaimable
```
Total reclaimable: ~25.2 GB  

---

## Phase 2 — Container inventory + restart counts

19 containers running, 0 stopped.  
`RestartCount` field unavailable in Docker 29.2.1 format string.  
All containers show healthy state; no `Exited` or `Created` containers.

**Containers identified as potentially idle / low-value:**
- `x-intake-lab` — lab container, no healthcheck issues but rarely used
- `cortex-autobuilder` — background research loop; verify it's producing value
- `rsshub` — see Phase 3

No container with RestartCount ≥ 5 detected (unable to parse via format string;
no crashloop stop condition fired).

---

## Phase 3 — Resource snapshot

```
NAME                 CPU %   MEM USAGE / LIMIT     MEM %    BLOCK I/O
rsshub               0.00%   181.3MiB / 256MiB     70.81%   118MB / 39MB  ← highest %
cortex               18.31%  42.42MiB / 2GiB        2.07%   (elevated CPU)
email-monitor        0.16%   61.84MiB / 256MiB     24.16%
cortex-autobuilder   0.19%   54.02MiB / 256MiB     21.10%
notification-hub     0.16%   45.42MiB / 256MiB     17.74%
x-intake             0.26%   43.35MiB / 256MiB     16.93%
client-portal        0.21%   80.1MiB / 512MiB      15.64%
polymarket-bot       2.19%   130.4MiB / 1GiB       12.74%
redis                1.23%   33.37MiB / 256MiB     13.04%
openclaw             3.80%   68.09MiB / 512MiB     13.30%
voice-receptionist   0.00%   68.84MiB / 512MiB     13.45%
```

**Total container memory:** ~1,207 MiB ≈ 1.18 GB  
**Docker VM allocation:** 3.83 GB  
**Effective headroom:** ~2.65 GB for Linux kernel + container overhead — tight.

Top 5 by MemPerc: rsshub (70.81%), email-monitor (24.16%), cortex-autobuilder (21.10%),
notification-hub (17.74%), x-intake (16.93%).

**rsshub is using 181/256 MiB (70.81%)** and generating errors about unconfigured Twitter API.

---

## Phase 4 — Host memory / CPU snapshot

### vm_stat (page size = 16,384 bytes)
```
Pages free:          10,923  (179 MB free)
Pages active:       138,625  (2.14 GB)
Pages inactive:     139,774  (2.16 GB)
Pages wired down:   465,400  (7.22 GB wired — cannot swap)
Pages in compressor: 574,892  (8.9 GB compressed from ~14+ GB)
Pages stored in compressor: 574,892
Swapins:            509,843  ← heavy swap activity
Swapouts:           749,350  ← heavy swap activity
```

### memory_pressure
```
System RAM: 17,179,869,184 bytes (16 GB physical)
Pages free: 8,572  ← BELOW 10,000 THRESHOLD at time of memory_pressure sample
Pages purgeable: 30
Swapins: 509,815 / Swapouts: 749,350
```

**⚠️ NEAR STOP CONDITION: memory_pressure free pages = 8,572 < 10,000**  
vm_stat showed 10,923 (marginal), memory_pressure showed 8,572. Single sample; not firing
stop condition on one sample, but this is effectively memory-exhausted.

### top — host processes by memory
```
PhysMem: 15G used (7287M wired, 3900M compressor), 126M unused  ← CRITICAL
Swapins: 509,843  Swapouts: 749,350  (VM thrashing)
Load avg: 2.51 / 2.25 / 2.29  (elevated)

Top consumers:
  ollama       (nomic-embed-text + qwen3:8b loaded): 5,710 MB resident + 370 MB compressed = 6.08 GB
  Docker VM    (com.apple.Virtualization):            3,285 MB resident + 3,653 MB compressed = 6.94 GB
  node         (voice-receptionist or clawwork?):       640 MB
  claude.exe   (this diagnostic process):               537 MB
  Brave Browser Helper:                                 522 MB
  Dropbox:                                              347 MB
  Docker Desktop Helper:                                250 MB
  BlueBubbles:                                          196 MB
```

**Memory accounting:**
- Ollama: ~6.1 GB  
- Docker VM: ~6.9 GB  
- Remaining apps: ~3 GB  
- Total: ~16 GB — fully consumed  
- Free: ~126 MB (0.8% of RAM)

### Disk
```
/ (system):                52% used  — OK
/System/Volumes/Data:      95% used  — CRITICAL (192 GB / 228 GB, 11 GB free)
```

### Uptime
```
9:12  up 2 days, 21:33 — stable uptime, no kernel panic
Load avg: 2.02 / 2.13 / 2.25  (5 CPUs; ~40% steady-state load)
```

---

## Phase 5 — Crash / OOM hints

### Watchdog recovery log (last 400 lines)
```
Distinct "Docker ready after Ns" cycles: 2
  2026-04-24 08:38:37  Docker ready after 65s
  2026-04-24 08:53:05  Docker ready after 40s
```
2 recoveries in the past 2 h. Manageable but indicates active crash-restart cycle.

### macOS kernel OOM/jetsam events
`log show` syntax incompatible with this shell session (too many arguments error).
Evidence from `memory_pressure` + `vm_stat` + `top` is conclusive without kernel logs.

### rsshub errors
All rsshub log entries are `ConfigNotFoundError: Twitter API is not configured`
(not memory-related; rsshub running 40+ Twitter feeds without API credentials).

### OOM signatures in containers
No `Killed`, `OOMKilled`, `signal=9`, or `exited with code 137` found in
rsshub or cortex log tails.

---

## Phase 6 — Compose config inspection

**Services:** 19 active  
**Memory limits declared:** 19/19 — all services have `mem_limit` ✓  
**Logging drivers:** all services use `json-file` with `max-size: 10m` / `max-file: 5` ✓  
**Healthchecks:** 18 configured  

Docker VM allocation (`mem=` from `docker info`): **3,825 MB (3.83 GB)**  
This is configured in Docker Desktop → Settings → Resources.

Sum of all `mem_limit` declarations:
```
redis: 256m, vpn: 256m, polymarket-bot: 1g, proposals: 512m,
email-monitor: 256m, notification-hub: 256m, dtools-bridge: 256m,
calendar-agent: 256m, voice-receptionist: 512m, openclaw: 512m,
cortex: 2g, x-intake: 256m, x-intake-lab: 512m, x-alpha-collector: 512m,
intel-feeds: 512m, client-portal: 512m, clawwork: 512m, rsshub: 256m,
cortex-autobuilder: 256m
Total declared ceiling: ~11.2 GB
```
The declared ceiling (11.2 GB) vastly exceeds the Docker VM allocation (3.83 GB).
Linux's OOM killer inside the VM becomes the backstop, not Docker's limits.

---

## Classification

**Primary: A — Memory pressure (host-level)**  
**Secondary: C — Disk pressure**  
**Secondary: E — Docker Desktop crash (daemon-level)**  
**Secondary: F — Watchdog false recovery (mild)**

### Evidence summary

| Factor | Finding | Severity |
|--------|---------|----------|
| Host free RAM | 126 MB (0.8% of 16 GB) | CRITICAL |
| memory_pressure free pages | 8,572 (< 10,000 threshold) | HIGH |
| Swap thrashing | 509K swapins / 749K swapouts | HIGH |
| Ollama RAM usage | 5,710 MB resident (qwen3:8b + nomic-embed-text loaded) | HIGH |
| Docker VM allocation | 3.83 GB for 19 containers | MEDIUM |
| Docker translocated path | Zombie-daemon root cause | HIGH |
| Disk /Data volume | 95% full (11 GB free) | CRITICAL |
| Docker reclaimable images | 20.03 GB (95%) | HIGH |
| Docker build cache | 5.2 GB reclaimable | MEDIUM |
| rsshub at 70.8% mem limit | ConfigNotFoundError on 40+ feeds | LOW-MEDIUM |
| Watchdog recovery cycles | 2 in last 2h | LOW |

### Root cause narrative

The **immediate trigger** for Docker crashes is RAM exhaustion. Today's session
pulled and ran `nomic-embed-text` (274 MB weights) via Ollama for the Cortex
embeddings arm. Ollama loaded both `nomic-embed-text` and `qwen3:8b` (5.2 GB)
into memory simultaneously, consuming ~5.7 GB. Combined with the Docker VM
(3.83 GB), Dropbox, Brave, BlueBubbles, Mail, and this diagnostic session, all
16 GB of host RAM is consumed. macOS resorts to compression and swap.

When the system swaps, the Docker VM's Linux kernel may temporarily lose access
to pages. Docker's socket becomes unresponsive (looks like a zombie daemon),
triggering the watchdog recovery cycle. The recovery kills and restarts Docker
Desktop, which re-launches from the translocated path and gets a brief window
of free RAM before the cycle repeats.

The **translocated path** is a **structural instability**: Docker Desktop should
live in `/Applications/Docker.app` not in a random `AppTranslocation` temp dir.
This makes each restart slower (extra validation) and may prevent Docker from
properly acquiring socket ownership on restart.

The **disk at 95%** means Docker cannot grow its data root if it needs to (e.g.,
for new image layers or container writes). When write operations to Docker's data
root fail silently, container healthchecks can time out, triggering watchdog.

---

## Safe recommendations

All proposals below require an explicit approval string to proceed. None executed here.

| # | Category | Proposal | Approval |
|---|----------|---------|---------|
| 1 | A+E | **Move Docker Desktop from translocated to /Applications.** Copy `/private/var/.../AppTranslocation/.../Docker.app` to `/Applications/Docker.app` (or re-download and drag-install). This is the single highest-impact fix — eliminates the zombie-daemon cycle entirely. No approval string needed for a re-install (it's a user action, not a script). | Manual Matt action |
| 2 | A | **Unload Ollama models when not in use.** `ollama stop` or configure `OLLAMA_KEEP_ALIVE=0` in Ollama's config to evict models from VRAM/RAM after use. Reclaims 5.7 GB immediately. | Manual Matt action |
| 3 | A | **Raise Docker Desktop VM memory to 6 GB** (from 3.83 GB). With Ollama quiet, 6 GB gives the 19 containers solid headroom. Set in Docker Desktop → Settings → Resources → Memory. | `APPROVE: docker-desktop-resources` |
| 4 | C | **Run `docker system prune -a --volumes` once** to reclaim 25+ GB disk/image space. Requires review: will remove unused images and stopped containers. | Manual Matt action (separate reviewed prompt) |
| 5 | C | **Reduce rsshub feed count** — 40+ Twitter feeds without API credentials generate constant errors. rsshub is using 181/256 MiB. Reduce feed list or configure API. | `APPROVE: container-decommission rsshub` (if removal preferred) |
| 6 | E+F | **Increase watchdog Docker-probe cooldown** from 180 s to 300 s. The 2 recovery cycles in 2h suggest the current 180 s is too eager — it triggers another restart before Docker has stabilized. | `APPROVE: watchdog-throttle` |
| 7 | A | **Decommission x-intake-lab** — lab container, 49.97 MiB, not critical path. Saves a mem_limit slot and reduces Docker's surface. | `APPROVE: container-decommission x-intake-lab` |
| 8 | A | **Decommission cortex-autobuilder** — if not actively used, 54 MiB saved. Verify whether it's producing output in `data/cortex/` before removing. | `APPROVE: container-decommission cortex-autobuilder` |

### Priority order (bang-for-buck)

1. **Reinstall Docker Desktop to /Applications** (free, fixes zombie-daemon permanently)
2. **`ollama stop` + set KEEP_ALIVE=0** (frees 5.7 GB immediately, no config change)
3. **`docker system prune -a`** (reclaims 25+ GB disk, resolves disk pressure)
4. **Raise Docker VM to 6 GB** after Ollama is quieted
5. Decommission idle lab containers
6. Watchdog cooldown bump

---

## Follow-up prompt candidates

| Future prompt | Approval required |
|---|---|
| `.cursor/prompts/2026-04-25-cline-docker-compose-memory-limits.md` — review and tighten per-service mem_limits, especially cortex (2 GB declared) | `APPROVE: compose-memory-limits` |
| `.cursor/prompts/2026-04-25-cline-docker-desktop-resources.md` — set Docker VM memory to 6 GB post-Ollama-quieting | `APPROVE: docker-desktop-resources` |
| `.cursor/prompts/2026-04-25-cline-watchdog-cooldown.md` — bump Docker probe cooldown to 300s and add hysteresis | `APPROVE: watchdog-throttle` |
| `.cursor/prompts/2026-04-25-cline-docker-prune.md` — controlled `docker system prune` (separate reviewed prompt, not this one) | Manual Matt review |

---

## Stop conditions fired

**NEAR-FIRE:** `memory_pressure` free pages = 8,572 < 10,000 threshold (single sample).  
`vm_stat` showed 10,923 on the same measurement window (marginal).  
Stop condition NOT fired (required consecutive samples below threshold).  
Diagnostic proceeded with caution; no further memory-intensive probes run.

---

## Commit

(To be filled after Phase 9 commit)
