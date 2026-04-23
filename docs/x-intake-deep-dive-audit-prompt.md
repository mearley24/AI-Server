# X-Intake Deep-Dive Audit Prompt

A full audit + design prompt for the X-intake deep-dive pipeline, the BlueBubbles/iMessage `Reply 1/2/3` action loop, and an isolated Docker testbed container lives at:

```
.cursor/prompts/audit-x-intake-deep-dive-reply-actions-and-docker-testbed.md
```

It is **audit + design only** — no runtime behavior changes, no secrets inspection, no outbound messages. Deliverables are a written audit under `docs/audits/`, a machine-readable action schema under `config/` (or `ops/`), and a verification artifact under `ops/verification/`.

## Run it

Via the standard dispatch wrapper (preferred — logs to `ops/verification/dispatch-*.txt`):

```bash
bash scripts/ai-dispatch.sh run-prompt .cursor/prompts/audit-x-intake-deep-dive-reply-actions-and-docker-testbed.md
```

Or directly against Claude 1M if you want to bypass the wrapper:

```bash
cat .cursor/prompts/audit-x-intake-deep-dive-reply-actions-and-docker-testbed.md \
  | claude --model 'claude-sonnet-4-6[1m]' --print
```

## What you get back

- `docs/audits/x-intake-deep-dive-audit.md`
- `config/reply_actions.schema.json` (or `ops/reply_actions.schema.json`)
- `ops/verification/reply-actions-design-verification.md`
- A `STATUS_REPORT.md` entry pointing to the above
- A commit + push to `origin/main`

## Guardrails baked into the prompt

- No implementation beyond the artifacts above.
- No secrets read or printed.
- No outbound messages (iMessage, BlueBubbles, X).
- No interactive commands (`tail -f`, `watch`, editors, container shells).
- Risky reply-actions (anything trading / money / external-send) route through the existing approvals flow; the prompt does not invent a new one.
