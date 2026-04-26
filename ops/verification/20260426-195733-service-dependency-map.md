# Verification — Service Dependency Map + Recovery Actions v1
**Date:** 2026-04-26T19:57:33Z
**Author:** Claude Sonnet 4.6

## Endpoint Output (sample — Docker degraded)

### GET /api/watchdog/status (degraded service with enrichment)
```json
{
    "status": "degraded",
    "degraded_count": 1,
    "services": [
        {
            "name": "Docker engine",
            "key": "docker",
            "state": "degraded",
            "severity": "high",
            "event_type": "recovery",
            "last_seen": "2026-04-26T19:52:30Z",
            "details": "Watchdog recovery 0.1h ago",
            "dependencies": [],
            "downstream_impacts": ["ALL containers"],
            "impact_summary": "All Docker services offline — complete system shutdown",
            "suggested_checks": ["docker ps"],
            "suggested_recovery": "scripts/docker-recover.sh",
            "recovery_risk": "high",
            "recovery_notes": "Only run docker-recover.sh if docker ps fails for 30+ seconds.",
            "should_auto_run": false
        }
    ]
}
```

Note: Docker marked degraded because cortex was force-recreated during testing (watchdog records container recovery events). Docker itself is healthy — this is the intended behavior showing the enrichment pipeline working on a real event.

## Services Mapped

26 services in `ops/service_dependency_map.json` + embedded `_SERVICE_DEP_MAP` in `cortex/engine.py`:

| Service | Risk | Key Impacts |
|---------|------|-------------|
| redis | medium | All 14+ dependents lose cache/queue |
| cortex | low | x-intake, notification-hub, client-portal |
| x-intake | low | reply suggestions, message routing |
| openclaw | low | voice-receptionist, auto-response, briefings |
| clawwork | low | openclaw agents |
| bluebubbles | medium | ALL iMessage I/O |
| ollama | low | cortex LLM drafts (graceful degradation) |
| docker | **high** | ALL containers |
| vpn | low | polymarket-bot |
| polymarket-bot | low | prediction market positions |
| notification-hub | low | alert delivery |
| voice-receptionist | low | inbound calls |
| email-monitor | low | email dashboard |
| calendar-agent | low | calendar dashboard |
| proposals | low | proposal generation |
| intel-feeds | low | market intelligence feed |
| x-alpha-collector | low | X.com data collection |
| tailscale | medium | remote access |
| containers | medium | bulk container recovery event |
| task-runner | low | scheduled automation |
| bob-watchdog | low | auto-recovery |
| rsshub | low | intel-feeds RSS |
| client-portal | low | client dashboard |
| dtools-bridge | low | Control4 tooling |
| cortex-autobuilder | low | auto-deploys |

## Key Design Decisions

1. **Embedded Python dict** — `_SERVICE_DEP_MAP` in `engine.py` mirrors the JSON file. Avoids needing a new Docker volume mount; container already has `engine.py` bundled.
2. **Key normalisation** — `x_intake` (underscore, from state file) → `x-intake` (hyphen, dep map key) handled by `_dep_map_lookup()`.
3. **Enrichment only for degraded** — ok services get no enrichment fields, keeping payload small.
4. **should_auto_run: false always** — enforced in `_enrich_with_deps()`, never toggles true.
5. **Unknown service keys** — return valid empty enrichment, no crash.

## Dashboard Changes

- Header banner now shows service names: "⚠ 1 degraded: Docker engine"
- Degraded service cards show:
  - Impact summary (yellow text)
  - Downstream impacts list
  - Check command + copy button (clipboard icon)
  - Recovery command + copy button + risk badge [HIGH/MEDIUM/LOW]
  - Recovery notes
- Copy buttons call `_wdCopyCmd()` via `navigator.clipboard.writeText()`
- No execute button — recommendations only

## Files Changed

| File | Change |
|------|--------|
| `ops/service_dependency_map.json` | New — 26 services with deps, impacts, commands, risk |
| `cortex/engine.py` | Added `_SERVICE_DEP_MAP` dict, `_dep_map_lookup()`, `_enrich_with_deps()`; called in `watchdog_status()` |
| `cortex/static/dashboard.js` | Added `_RISK_COLOR`, `_wdCopyCmd()`, `_wdDegradedCard()` helper; updated `renderWatchdog()` banner + card rendering |
| `cortex/static/dashboard.css` | Added `.wd-degraded-card`, `.wd-cmd-row`, `.wd-cmd`, `.wd-copy-btn` styles |
| `ops/tests/test_watchdog_status.py` | Added `TestServiceDependencyMap` (8 new tests) |
| `ops/verification/20260426-195733-service-dependency-map.md` | This file |

## Tests Run

```
python3 -m pytest ops/tests -q
981 passed, 4 warnings in 13.56s
```

New tests (8 in `TestServiceDependencyMap`):
- `test_dep_map_contains_expected_services` — core services present
- `test_docker_is_high_risk` — docker marked high
- `test_degraded_service_includes_impact_fields` — enrichment fields populated
- `test_should_auto_run_is_always_false` — never auto-executes
- `test_docker_degraded_marked_high_risk` — docker degraded → recovery_risk=high
- `test_x_intake_key_normalisation` — underscore→hyphen resolved correctly
- `test_unknown_service_key_no_crash` — unknown keys handled gracefully
- `test_ok_services_have_no_dep_fields` — ok services not enriched

## No Sends / No Auto-Execution

All recovery actions are strings in the API response. No commands are executed by the server or dashboard. `should_auto_run: false` is hardcoded. The dashboard renders copy-to-clipboard buttons only — no execute buttons.
