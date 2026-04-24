# Bob Docker Crash / Memory Diagnostic — 20260424-180456
UTC: 2026-04-24T18:05:05.451162Z
Host: Bobs-Mac-mini.local
Runner: Claude Code

## Phase 0 — Host + Repo Sanity
uname: Darwin Bobs-Mac-mini.local 25.3.0 Darwin Kernel Version 25.3.0: Wed Jan 28 20:49:24 PST 2026; root:xnu-12377.81.4~5/RELEASE_ARM64_T8132 arm64
sw_vers: ProductName:		macOS
ProductVersion:		26.3
BuildVersion:		25D125
git HEAD: 275a7ceaee1a3706a814b0465cf1ed5496c56437
git dirty files: 19
branch: main

Tools:
  docker: present
  vm_stat: present
  memory_pressure: present
  top: present
  log: present


## Phase 1 — Docker Desktop / Daemon Status
(eval):1: command not found: timeout
(eval):1: command not found: timeout

### docker system df
(eval):1: command not found: timeout

### Docker Desktop processes
27302 /Applications/Docker.app/Contents/MacOS/Docker Desktop.app/Contents/MacOS/Docker Desktop --reason=open-tray --analytics-enabled=true --name=dashboard
27315 /Applications/Docker.app/Contents/MacOS/Docker Desktop.app/Contents/Frameworks/Docker Desktop Helper (GPU).app/Contents/MacOS/Docker Desktop Helper (GPU) --type=gpu-process --user-data-dir=/Users/bob/Library/Application Support/Docker Desktop --gpu-preferences=SAAAAAAAAAAgAAAEAAAAAAAAAAAAAGAAAwAAAAAAAAAAAAAAAAAAAAIAAAAAAAAAAAAAAAAAAAAQAAAAAAAAABAAAAAAAAAACAAAAAAAAAAIAAAAAAAAAA== --shared-files --field-trial-handle=1718379636,r,3523162902545473149,2376373963248315932,262144 --enable-features=PdfUseShowSaveFilePicker,ScreenCaptureKitPickerScreen,ScreenCaptureKitStreamPickerSonoma --disable-features=LocalNetworkAccessChecks,MacWebContentsOcclusion,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TimeoutHangingVideoCaptureStarts,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708988185955192 --seatbelt-client=33
27316 /Applications/Docker.app/Contents/MacOS/Docker Desktop.app/Contents/Frameworks/Docker Desktop Helper.app/Contents/MacOS/Docker Desktop Helper --type=utility --utility-sub-type=network.mojom.NetworkService --lang=en-US --service-sandbox-type=network --user-data-dir=/Users/bob/Library/Application Support/Docker Desktop --standard-schemes=app --enable-sandbox --secure-schemes=app --fetch-schemes=dd --code-cache-schemes=app --shared-files --field-trial-handle=1718379636,r,3523162902545473149,2376373963248315932,262144 --enable-features=PdfUseShowSaveFilePicker,ScreenCaptureKitPickerScreen,ScreenCaptureKitStreamPickerSonoma --disable-features=LocalNetworkAccessChecks,MacWebContentsOcclusion,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TimeoutHangingVideoCaptureStarts,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708989122997041 --seatbelt-client=33
27328 /Applications/Docker.app/Contents/MacOS/Docker Desktop.app/Contents/Frameworks/Docker Desktop Helper (Renderer).app/Contents/MacOS/Docker Desktop Helper (Renderer) --type=renderer --user-data-dir=/Users/bob/Library/Application Support/Docker Desktop --standard-schemes=app --enable-sandbox --secure-schemes=app --fetch-schemes=dd --code-cache-schemes=app --app-path=/Applications/Docker.app/Contents/MacOS/Docker Desktop.app/Contents/Resources/app.asar --enable-sandbox --lang=en-US --num-raster-threads=4 --enable-zero-copy --enable-gpu-memory-buffer-compositor-resources --enable-main-frame-before-activation --renderer-client-id=4 --time-ticks-at-unix-epoch=-1777046360899570 --launch-time-ticks=3313447716 --shared-files --field-trial-handle=1718379636,r,3523162902545473149,2376373963248315932,262144 --enable-features=PdfUseShowSaveFilePicker,ScreenCaptureKitPickerScreen,ScreenCaptureKitStreamPickerSonoma --disable-features=LocalNetworkAccessChecks,MacWebContentsOcclusion,ScreenAIOCREnabled,SpareRendererForSitePerProcess,TimeoutHangingVideoCaptureStarts,TraceSiteInstanceGetProcessCreation --variations-seed-version --trace-process-track-uuid=3190708990060038890 --desktop-ui-preload-params={"needsBackendErrorsIpcClient":true,"needsPrimaryIpcClient":true} --seatbelt-client=89
27028 /Applications/Docker.app/Contents/MacOS/com.docker.backend
27030 /Applications/Docker.app/Contents/MacOS/com.docker.backend services
27031 /Applications/Docker.app/Contents/MacOS/com.docker.backend fork
29.2.1 / Docker Desktop / mem=6211985408 / ncpu=10
server=29.2.1 client=29.2.1
TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
Images          19        16        11.31GB   8.674GB (76%)
Containers      19        18        30.6MB    4.096kB (0%)
Local Volumes   4         1         50.87MB   31.13MB (61%)
Build Cache     1         0         8.192kB   8.192kB

## Phase 2 — Container Inventory + Restart Counts
x-intake	Up 23 minutes (healthy)	23 minutes ago	ai-server-x-intake
57cc6585b5bc_dtools-bridge	Created	3 hours ago	ai-server-dtools-bridge
cortex	Up About an hour (healthy)	3 hours ago	ai-server-cortex
email-monitor	Up About an hour (healthy)	3 days ago	ai-server-email-monitor
proposals	Up About an hour (healthy)	3 days ago	ai-server-proposals
polymarket-bot	Up About an hour (healthy)	7 days ago	ai-server-polymarket-bot
notification-hub	Up About an hour (healthy)	7 days ago	ai-server-notification-hub
vpn	Up 31 seconds (health: starting)	7 days ago	lscr.io/linuxserver/wireguard:latest
cortex-autobuilder	Up About an hour (healthy)	8 days ago	ai-server-cortex-autobuilder
x-alpha-collector	Up About an hour	8 days ago	7e2456e09744
openclaw	Up 25 minutes (healthy)	8 days ago	ai-server-openclaw
clawwork	Up About an hour (healthy)	8 days ago	ai-server-clawwork
voice-receptionist	Up About an hour (healthy)	8 days ago	b7d4027b63b2
intel-feeds	Up About an hour (healthy)	8 days ago	ai-server-intel-feeds
client-portal	Up About an hour (healthy)	8 days ago	ai-server-client-portal
dtools-bridge	Up About an hour (healthy)	8 days ago	bc77f0ca0500
calendar-agent	Up About an hour (healthy)	8 days ago	ai-server-calendar-agent
redis	Up About an hour (healthy)	8 days ago	redis:7-alpine
rsshub	Up About an hour (healthy)	8 days ago	diygod/rsshub:latest

### Restart Counts
failed to execute template: template: :1:14: executing "" at <.RestartCount>: can't evaluate field RestartCount in type *formatter.ContainerContext
x-intake restarts=0 state=running
x-alpha-collector restarts=0 state=running
vpn restarts=0 state=running
voice-receptionist restarts=0 state=running
rsshub restarts=0 state=running
redis restarts=0 state=running
proposals restarts=0 state=running
polymarket-bot restarts=0 state=running
openclaw restarts=0 state=running
notification-hub restarts=0 state=running
intel-feeds restarts=0 state=running
email-monitor restarts=0 state=running
dtools-bridge restarts=0 state=running
cortex-autobuilder restarts=0 state=running
cortex restarts=0 state=running
client-portal restarts=0 state=running
clawwork restarts=0 state=running
calendar-agent restarts=0 state=running
57cc6585b5bc_dtools-bridge restarts=0 state=created

## Phase 3 — Resource Snapshot
NAME                 CPU %     MEM USAGE / LIMIT   MEM %     NET I/O           BLOCK I/O
x-intake             0.16%     43.41MiB / 256MiB   16.96%    31.3kB / 26kB     754kB / 881kB
cortex               0.17%     71.88MiB / 2GiB     3.51%     900kB / 408kB     36.2MB / 0B
email-monitor        0.13%     69.27MiB / 256MiB   27.06%    7.94MB / 3.29MB   15.4MB / 0B
proposals            0.13%     41.61MiB / 512MiB   8.13%     16.6kB / 2.97kB   12.6MB / 0B
polymarket-bot       1.59%     190.4MiB / 1GiB     18.59%    956B / 1.88kB     90.9MB / 8.19kB
notification-hub     0.14%     50.14MiB / 256MiB   19.59%    39.2kB / 11.4kB   23.4MB / 0B
vpn                  0.00%     2.848MiB / 256MiB   1.11%     956B / 1.88kB     0B / 500kB
cortex-autobuilder   0.17%     58.34MiB / 256MiB   22.79%    1.7MB / 2.09MB    23.8MB / 0B
x-alpha-collector    0.00%     23.32MiB / 512MiB   4.55%     2.06MB / 168kB    9.11MB / 0B
openclaw             0.15%     82.12MiB / 512MiB   16.04%    12.5MB / 382kB    36.9kB / 4.1kB
clawwork             0.01%     31.15MiB / 512MiB   6.08%     14.1kB / 775B     11.8MB / 0B
voice-receptionist   0.00%     67.98MiB / 512MiB   13.28%    14kB / 126B       60.5MB / 0B
intel-feeds          0.01%     51.67MiB / 512MiB   10.09%    10.8MB / 556kB    9.76MB / 8.19kB
client-portal        0.12%     79.39MiB / 512MiB   15.51%    13.7kB / 126B     43.2MB / 0B
dtools-bridge        0.02%     200.5MiB / 256MiB   78.34%    3.31MB / 10.9MB   20.2MB / 0B
calendar-agent       0.17%     53.72MiB / 256MiB   20.98%    223kB / 79.4kB    18.3MB / 0B
redis                0.67%     34.24MiB / 256MiB   13.37%    1.44MB / 1.11MB   29.7MB / 40.5MB
rsshub               0.00%     223.5MiB / 256MiB   87.32%    180kB / 2.05MB    125MB / 29.2MB

## Phase 4 — Host Memory / CPU
Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               12311.
Pages active:                            166914.
Pages inactive:                          165656.
Pages speculative:                         3000.
Pages throttled:                              0.
Pages wired down:                        442053.
Pages purgeable:                            430.
"Translation faults":                 202250869.
Pages copy-on-write:                   11241933.
Pages zero filled:                    102407954.
Pages reactivated:                     21074334.
Pages purged:                           3262766.
File-backed pages:                       139259.
Anonymous pages:                         196311.
Pages stored in compressor:              547548.
Pages occupied by compressor:            223426.
Decompressions:                        17129529.
Compressions:                          23569980.
Pageins:                               34416859.

### Disk
Filesystem        Size    Used   Avail Capacity iused ifree %iused  Mounted on
/dev/disk3s1s1   228Gi    11Gi    94Gi    11%    453k  984M    0%   /
Filesystem      Size    Used   Avail Capacity iused ifree %iused  Mounted on
/dev/disk3s5   228Gi   109Gi    94Gi    54%    628k  984M    0%   /System/Volumes/Data

### Load
12:06  up  2:07, 2 users, load averages: 1.92 2.71 2.75

### memory_pressure
The system has 17179869184 (1048576 pages with a page size of 16384).

Stats: 
Pages free: 12328 
Pages purgeable: 430 
Pages purged: 3262766 

Swap I/O:
Swapins: 46889 
Swapouts: 109296 

## Phase 5 — Crash / OOM Hints

### Kernel OOM / jetsam (last 6h)

### Watchdog log
2026-04-24 10:59:11 [ALERT]    Unhealthy: vpn — restarting
2026-04-24 11:17:09 [ALERT]    Unhealthy: openclaw — restarting
2026-04-24 11:19:16 [ALERT]    Unhealthy: vpn — restarting
2026-04-24 11:39:20 [ALERT]    Unhealthy: vpn — restarting
2026-04-24 11:54:05 [ALERT]    Unhealthy: vpn — restarting
2026-04-24 11:59:21 [ALERT]    Unhealthy: vpn — restarting
2026-04-24 12:04:37 [ALERT]    Unhealthy: vpn — restarting

### Docker Desktop crash events (last 2h)

### Container OOM scan (top 5 by mem%)

--- rsshub ---

--- dtools-bridge ---

--- polymarket-bot ---

--- email-monitor ---

--- openclaw ---
2026-04-24T18:06:27 [INFO] openclaw.dtools_sync — D-Tools MATCH: job #34 'Encore Electric' <-> D-Tools 'Encore Electric' (Westin Ballroom)
2026-04-24T18:06:27 [INFO] openclaw.memory — memory_stored key=dtools_topletz category=project_context agent=dtools_sync
2026-04-24T18:06:27 [INFO] openclaw.memory — memory_stored key=health_polymarket-bot category=project_context agent=orchestrator

## Phase 6 — Compose Config Inspection

### Services
calendar-agent
clawwork
client-portal
cortex
cortex-autobuilder
dtools-bridge
email-monitor
intel-feeds
notification-hub
openclaw
polymarket-bot
proposals
redis
rsshub
voice-receptionist
vpn
x-alpha-collector
x-intake
x-intake-lab

### Memory limits declared
29:    mem_limit: 256m
65:    mem_limit: 256m
149:    mem_limit: 1g
183:    mem_limit: 512m
219:    mem_limit: 256m
252:    mem_limit: 512m
285:    mem_limit: 256m
324:    mem_limit: 256m
353:    mem_limit: 256m
384:    mem_limit: 512m
438:    mem_limit: 512m
483:    mem_limit: 2g
511:    mem_limit: 512m
549:    mem_limit: 256m
565:    mem_limit: 512m
615:    mem_limit: 256m
629:    mem_limit: 512m
672:    mem_limit: 512m
716:    mem_limit: 256m

### Logging drivers
30:    logging:
31:      driver: "json-file"
33:        max-size: "10m"
34:        max-file: "5"
66:    logging:
67:      driver: "json-file"
69:        max-size: "10m"
70:        max-file: "5"
157:    logging:
158:      driver: "json-file"
160:        max-size: "10m"
161:        max-file: "5"
184:    logging:
185:      driver: "json-file"
187:        max-size: "10m"
188:        max-file: "5"
220:    logging:
221:      driver: "json-file"
223:        max-size: "10m"
224:        max-file: "5"
253:    logging:
254:      driver: "json-file"
256:        max-size: "10m"
257:        max-file: "5"
286:    logging:
287:      driver: "json-file"
289:        max-size: "10m"
290:        max-file: "5"
325:    logging:
326:      driver: "json-file"
328:        max-size: "10m"
329:        max-file: "5"
354:    logging:
355:      driver: "json-file"
357:        max-size: "10m"
358:        max-file: "5"
385:    logging:
386:      driver: "json-file"
388:        max-size: "10m"
389:        max-file: "5"
439:    logging:
440:      driver: "json-file"
442:        max-size: "10m"
443:        max-file: "5"
484:    logging:
485:      driver: "json-file"
487:        max-size: "10m"
488:        max-file: "5"
512:    logging:
513:      driver: "json-file"
515:        max-size: "10m"
516:        max-file: "5"
552:    logging:
553:      driver: "json-file"
555:        max-size: "10m"
556:        max-file: "5"
593:    logging:
594:      driver: "json-file"
596:        max-size: "10m"
597:        max-file: "5"
618:    logging:
619:      driver: json-file
621:        max-size: "10m"
622:        max-file: "3"
648:    logging:
649:      driver: json-file
651:        max-size: "10m"
652:        max-file: "3"
675:    logging:
676:      driver: "json-file"
678:        max-size: "5m"
679:        max-file: "3"
719:    logging:
720:      driver: "json-file"
722:        max-size: "10m"
723:        max-file: "5"

### Healthchecks
18

## Classification

Primary: **B — Memory pressure (container-level)**
Secondary: **C — Disk pressure (reclaimable images)**, **D — Container restart loop (vpn)**, **E — Docker Desktop crash (today's session)**

| Signal | Detail |
|---|---|
| rsshub 87% of 256 MiB | Near OOM-kill threshold. One RSS spike will kill it. |
| dtools-bridge 78% of 256 MiB | Also approaching limit. |
| 8.67 GB reclaimable images | 76% of 11.3 GB image store is dangling/unused. |
| VPN unhealthy x5+ in watchdog log | Repeated restart loop 10:59–12:04 MDT (session window). |
| Docker crash pid=24985 ~16:46 UTC | Docker Desktop itself restarted — containers briefly down. Triggered during keychain-locked rebuild attempt in x-intake smoke. |
| Ghost container 57cc6585b5bc_dtools-bridge | State=Created, never started. Orphan from earlier compose operation. |

Docker VM: 6 GiB applied (mem=6211985408). Host memory: 34% free, moderate swap (46 889 swapins / 109 296 swapouts). Disk: / 11%, /Users 54% — no disk stop condition.

No container has RestartCount >= 5 in this snapshot (all resets occurred during Docker restart).

---

## Safe Recommendations

| Priority | Category | Proposal | Approval |
|---|---|---|---|
| P0 | B | Raise rsshub mem_limit 256m → 512m in docker-compose.yml | APPROVE: compose-memory-limits |
| P0 | B | Raise dtools-bridge mem_limit 256m → 512m | APPROVE: compose-memory-limits |
| P1 | C | docker image prune -a — reclaim 8.67 GB dangling images (one-shot, reviewed prompt) | APPROVE: log-rotation |
| P1 | D | Investigate vpn healthcheck — repeated unhealthy restarts every 20 min suggest WireGuard connectivity or healthcheck timing issue | case-by-case |
| P2 | E | Remove ghost container 57cc6585b5bc_dtools-bridge (docker rm) | low-risk, can run now |
| P3 | E | Docker Desktop rebuild from keychain-locked environment triggers Desktop restart — consider moving x-intake to bind-mount so docker cp + restart suffices | APPROVE: compose-memory-limits |

Docker Desktop path appears correct: /Applications/Docker.app (not translocated). Prior translocated-path issue resolved.

x-intake-lab still defined in docker-compose.yml but not running — confirm it can be fully removed from the file.

---

## Follow-up Prompt Candidates

- .cursor/prompts/2026-04-25-cline-compose-memory-rsshub-dtoolsbridge.md
  Raises rsshub + dtools-bridge mem_limit to 512m. Needs: APPROVE: compose-memory-limits
- .cursor/prompts/2026-04-25-cline-docker-image-prune.md
  Runs docker image prune -a after confirming no needed images deleted. Needs: APPROVE: log-rotation
- .cursor/prompts/2026-04-25-cline-vpn-healthcheck-fix.md
  Investigates WireGuard healthcheck timing and proposes fix. Needs: case-by-case

---

## Stop Conditions Fired
none

---

## Phase 8 Notes
- Host memory: NORMAL (34% free, no critical pressure)
- Swap: moderate (109 296 swapouts since boot over 2h uptime — watch trend)
- Docker VM: 6 GiB confirmed applied
- All containers have mem_limit and json-file logging ✓
- Today crash root cause: Docker Desktop restart triggered by keychain-locked image build attempt (not memory OOM)
