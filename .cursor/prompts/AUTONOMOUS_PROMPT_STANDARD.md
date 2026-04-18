# Autonomous Prompt Standard — Symphony AI-Server

Spec for every `cline-prompt-*.md` that runs under
`AUTO_APPROVE = true` inside this repo. Non-autonomous prose (playbooks,
design notes) do not need to follow this shape.

Every autonomous prompt **must** include the four metadata lines below in
its opening block so `scripts/build_prompt_index.py` can render
`.cursor/prompts/INDEX.md` deterministically.

## Required metadata

```
<!-- autonomy: start -->
Category: <one of: ops, trading, messaging, web, data, knowledge, safety, meta>
Risk tier: <low | medium | high>
Trigger:   <manual | realized-change | schedule:<cron-like> | webhook:<name>>
Status:    <active | done | retired>
<!-- autonomy: end -->
```

- `Category` mirrors the category-campaign buckets that already exist in
  `ops/verification/20260417-101800-category-campaign-final.txt`. Use the
  closest match; ops is the catch-all.
- `Risk tier` matches the tiers defined in `CLAUDE.md` (Standing Approval
  table) and `ops/AGENT_VERIFICATION_PROTOCOL.md`.
- `Trigger` is the thing that fires this prompt. For prompts that run
  only when a realized change lands (STATUS_REPORT edit, new
  `ops/realized_changes/*.change` file, etc.) use `realized-change`.
- `Status` lets the index hide retired prompts without deleting them.

## Required body structure

Every autonomous prompt must have these section headings, in this order:

1. **Goal** — one paragraph; what the prompt accomplishes.
2. **Preconditions** — files to read first, health checks to run.
3. **Operating mode** — AUTO_APPROVE flag, hard bans (no heredocs, no
   interactive editors, bounded commands only), and the verification-
   to-file-then-commit contract.
4. **Step plan** — numbered phases; each phase is bounded and does not
   require human input between steps.
5. **Guardrails** — risk-tier-specific bans (off-limits files / services /
   approvals required).
6. **Final report** — what to write to
   `ops/verification/YYYYMMDD-HHMMSS-<topic>.txt`, commit, and push.

A prompt that deviates from this shape is still runnable, but it will
render with a `[NON-STANDARD]` note in `INDEX.md` and should be brought
back in line on its next edit.

## Shell rules inside prompts

When a prompt includes a bash snippet that Matt or an agent will paste
into a terminal, the snippet must follow `.clinerules`:

- No heredocs (`<<EOF`, `<<'EOF'`, `<< 'DELIM'`).
- No multi-line quoted strings.
- No inline interpreters (`python3 <<EOF`, `node -e 'multi\nline'`).
- No interactive editors (vim, nano, `crontab -e`).
- No long-running watch modes (`tail -f`, `--watch`, `npm run dev`).
- No inline comments inside the fenced block — put commentary outside.

Safe patterns:

- `python3 -c "open('file','w').write('line1\\nline2\\n')"`
- `printf 'line1\nline2\n' > file`
- `echo 'line1' > file && echo 'line2' >> file`
- `curl -d @file http://host:port/path` (never inline JSON).

## Verification contract

Every autonomous prompt ends with a tee-to-file + commit + push block so
another agent can read the result without Matt pasting output. The tail
pattern is spelled out in `ops/AGENT_VERIFICATION_PROTOCOL.md`.

## How to retire a prompt

Set `Status: retired` in the metadata block and move the file to
`.cursor/prompts/DONE/` on its next edit. The index builder will drop
retired prompts from the active table but keep them listed under an
"Archive" section so the audit trail survives.
