# Messaging Alerts — what should ping Matt

Purpose: a single source of truth for which failure modes should
produce an outbound alert and via which channel. Actual wiring may
be partial — this is the plan.

Channel assumption: all alerts go via `notification-hub` (port 8095).
Use `scripts/notify-hub-post.sh <channel> <title> <body>` to send.

## Legend

| Priority | Meaning |
|---|---|
| critical | Wake Matt: money risk, customer-visible outage, data loss |
| warn | Alert during business hours only |
| info | Log + dashboard only; no push |

## Alert matrix

| Condition | Priority | Channel | Source hook | Status |
|---|---|---|---|---|
| `ops/task_runner_health.py` exits 1 (unhealthy) | warn | imessage | launchd plist StandardErrorPath + watchdog | TODO |
| `scripts/verify-deploy.sh` FAIL (any service down) | warn | imessage | CI hook / manual run | TODO |
| Redis PING fails or static IP drifts | critical | imessage | `scripts/bob-watchdog.sh` already alerts in log; wire to hub | TODO |
| polymarket-bot loses VPN / container exits | critical | imessage | polymarket-bot exit hook → bob-watchdog | TODO |
| BlueBubbles watchdog relaunches (>3 in 10 min) | warn | imessage | launchd StandardErrorPath + counter | TODO |
| email-monitor Zoho IMAP disconnected > 10 min | warn | imessage | `email-monitor/monitor.py` → ops:email_action | partial |
| Cortex `/remember` 5xx rate > 1/min for 5 min | warn | imessage | cortex dashboard metric + threshold | TODO |
| Trading: Polymarket wallet < $10 USDC | warn | imessage | polymarket-bot bankroll check | TODO |
| Trading: Redeemer fails 3 cycles in a row | warn | imessage | redeemer loop error path | TODO |
| Follow-up engine fires (client email sent) | info | imessage | STATUS update to Matt | TODO |
| Email bid invite detected (BID / PASS / REVIEW) | info | imessage | `email-monitor/bid_triage.py` — active | active |
| Pending approvals > 25 queued | warn | imessage | approval_drain pre-check | TODO |
| Task-runner `failed/` grows by 2+ in one tick | warn | imessage | task_runner post-move hook | TODO |
| Task-runner `rejected/` grows by 1+ in one tick | warn | imessage | task_runner post-move hook | TODO |
| Dashboard offline (port 8102 health != 200) | warn | imessage | bob-watchdog — exists, log-only | partial |
| voice-receptionist call volume > 3/hour after hours | info | imessage | voice-receptionist hook | TODO |

## Silent-by-design (do NOT alert)

- `events:log` 1000-entry cap rotation (expected behavior).
- Preflight whitelisted auto-resolves (expected, already logged).
- x-intake URL analysis success (normal traffic).
- `follow_up_tracker` per-tick writes (too noisy).
- Cortex memory growth (monitored on dashboard, not alerted).

## Wiring pattern

Each TODO row above should be hooked via one of:

- **launchd plist exit code** → wrapper script calls `notify-hub-post.sh`.
- **Python service hook** → direct `httpx.post(NOTIFY_URL, json=...)`
  inside the service, on the failure path.
- **Redis channel** → worker subscribed to `ops:alerts` pushes to hub.

Prefer the third pattern for anything publishing on `events:log`
anyway — it keeps the dispatch surface small.

## Throttling

- Any one condition emits at most one alert per 15 min.
- `critical` ignores throttle on the first fire; warns thereafter.
- State file: `data/notification-hub/alert_throttle.json`.

## Approval impact

Alerts are internal-only (Matt). They do NOT trigger the high-risk
"customer-visible outbound" approval gate (CLAUDE.md). A separate
confirmation is still required for any automated send to a client.
