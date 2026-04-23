# Network Monitoring v2 — Cline Dispatch

Paste this into **Cline → New Task** on Bob. The full prompt lives at
`.cursor/prompts/audit-and-design-network-monitoring-v2.md` in this
repo; Cline will read it from there.

This run is **audit + design only**. No implementation, no launchd
arm, no Docker start, no external sends, no secrets printed.

## Exact Cline prompt (copy/paste)

```
Read /CLAUDE.md, AGENTS.md, .clinerules, ops/AGENT_VERIFICATION_PROTOCOL.md,
ops/GUARDRAILS.md, and .cursor/prompts/AUTONOMOUS_PROMPT_STANDARD.md first.
Then execute .cursor/prompts/audit-and-design-network-monitoring-v2.md
end-to-end on Bob.

This is Network Monitoring v2 — audit + design only. Start with the
visibility audit in Step 1 before any architecture work. Treat the
existing pieces as source of truth: tools/network_guard_daemon.py,
tools/network_dropout_watch.py, setup/nodes/node_health_monitor.py,
api/host_modules/network.py, setup/launchd/com.symphony.network-guard.plist,
data/network_guard_*, data/network_watch/*, knowledge/network/*.

Do NOT implement the monitor. Do NOT load/kickstart any launchd job.
Do NOT start Docker services. Do NOT send external messages. Do NOT
print or decode secrets. Redact MACs, full IPs, SSIDs, BSSIDs in any
committed doc. Use only bounded commands (timeout, -c N, --lines,
head, sed -n); no tail -f, no --watch, no interactive editors.

Deliverables: docs/audits/network-monitoring-v2-visibility-audit.md,
.cursor/prompts/implement-network-monitoring-v2-phase-1.md,
ops/verification/YYYYMMDD-HHMMSS-network-monitoring-v2-audit.txt,
STATUS_REPORT.md update, then commit with message
"docs(network-v2): visibility audit + hybrid architecture design"
and push origin main.

Final report to stdout: existing stack synthesis, what Bob can
actually see, recommended hybrid architecture, bumps / [NEEDS_MATT],
Phase-1 prompt path, verification artifact path, commit hash, push
result.
```

## ai-dispatch fallback

If Cline is unavailable on Bob, dispatch via ai-dispatch to a local
Claude Code session on Bob with the same body. Keep the body byte-for-
byte identical so the prompt hash matches any audit logging.

```
ai-dispatch --host bob --agent claude-code --prompt-file .cursor/prompts/audit-and-design-network-monitoring-v2.md --risk-tier low --category ops
```

If `ai-dispatch` is not installed or the host shim isn't wired yet,
fall back to running the prompt directly on Bob inside Cline (primary
path above). Do not run this prompt from the Docker container — the
visibility audit requires macOS-native interfaces.

## Scope reminder

- Phase 0 (this run): audit + design, no behavior change.
- Phase 1 (next run): implementation, gated on the audit's
  `[NEEDS_MATT]` items (sudoers for tcpdump, launchd arm, any
  router/switch API creds).
- Phase 2+ (future): optional ntopng/netdata, router/SPAN integration,
  richer Cortex widgets — only after Phase 1 verifies Bob-native
  sensor coverage.
