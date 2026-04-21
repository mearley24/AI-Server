# Prompt AA — Claude Max Integration & LiteLLM Proxy Setup

<!-- autonomy: start -->
Category: ops
Risk tier: low
Trigger: manual
Status: active
<!-- autonomy: end -->

## Goal

Claude Max (subscription) is logged in via Claude CLI. This prompt verifies the full auth chain, wires Cline to use Claude Code as its provider (zero API cost until May 11), installs a LiteLLM proxy so all internal Docker services call Claude through the subscription instead of burning Anthropic API key credits, and documents the final state to the verification log.

## Preconditions

Read these files before starting:
- `CLAUDE.md` — service table, ports, stack overview
- `docker-compose.yml` — every service that makes LLM calls
- `.env` or secrets store — check which services have `ANTHROPIC_API_KEY` or `OPENAI_BASE_URL` set

Run preflight checks:
```zsh
claude --version
claude -p "say hello and confirm Max subscription is active"
docker compose ps --format "table {{.Name}}\t{{.Status}}"
tailscale status
```

If `claude -p` responds without a payment prompt, Max is active. Continue. If it asks for payment, stop and report in the verification log.

## Operating mode

AUTO_APPROVE: true for all read, install, config-write, and git operations.
No heredocs. No interactive editors. No long-running watch modes.
All output tee'd to verification file before commit.

## Step Plan

### Phase 1 — Verify Claude CLI Auth

```zsh
claude --version 2>&1 | tee /tmp/claude_auth_check.txt
claude -p "respond with: MAX_ACTIVE" 2>&1 | tee -a /tmp/claude_auth_check.txt
which claude | tee -a /tmp/claude_auth_check.txt
```

Confirm the output contains a version number and `MAX_ACTIVE`. If not, stop here and report.

### Phase 2 — Verify All Other Auth Dependencies

Check each of the following and append results to `/tmp/claude_auth_check.txt`:

```zsh
gh auth status 2>&1 | tee -a /tmp/claude_auth_check.txt
git -C . remote -v 2>&1 | tee -a /tmp/claude_auth_check.txt
docker info --format "{{.ID}}" 2>&1 | tee -a /tmp/claude_auth_check.txt
tailscale status 2>&1 | tee -a /tmp/claude_auth_check.txt
```

Also verify these `.env` keys exist (print key names only, never values):
```zsh
grep -E "^(ANTHROPIC_API_KEY|OPENAI_API_KEY|POLYMARKET|X_API|TWITTER)" .env 2>/dev/null | sed 's/=.*/=SET' | tee -a /tmp/claude_auth_check.txt
```

Note any key that is missing or shows as blank.

### Phase 3 — Install LiteLLM Proxy

Install LiteLLM if not already present:
```zsh
pip3 install litellm 2>&1 | tail -5 | tee -a /tmp/claude_auth_check.txt
litellm --version 2>&1 | tee -a /tmp/claude_auth_check.txt
```

Create the LiteLLM config file at `ops/litellm_config.yaml`. Use this exact content:
```zsh
printf 'model_list:\n  - model_name: claude-opus\n    litellm_params:\n      model: claude-opus-4-20250514\n      api_base: http://localhost:8080\n  - model_name: claude-sonnet\n    litellm_params:\n      model: claude-sonnet-4-20250514\n      api_base: http://localhost:8080\nlitellm_settings:\n  drop_params: true\n  set_verbose: false\n' > ops/litellm_config.yaml
```

Create a launchd plist to keep the proxy running on Bob at boot:
```zsh
printf '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n<dict>\n  <key>Label</key>\n  <string>ai.symphony.litellm-proxy</string>\n  <key>ProgramArguments</key>\n  <array>\n    <string>/usr/local/bin/litellm</string>\n    <string>--config</string>\n    <string>/Users/matthewearley/AI-Server/ops/litellm_config.yaml</string>\n    <string>--port</string>\n    <string>4000</string>\n  </array>\n  <key>RunAtLoad</key>\n  <true/>\n  <key>KeepAlive</key>\n  <true/>\n  <key>StandardOutPath</key>\n  <string>/tmp/litellm_proxy.log</string>\n  <key>StandardErrorPath</key>\n  <string>/tmp/litellm_proxy_err.log</string>\n</dict>\n</plist>\n' > ~/Library/LaunchAgents/ai.symphony.litellm-proxy.plist
```

Load it:
```zsh
launchctl load ~/Library/LaunchAgents/ai.symphony.litellm-proxy.plist 2>&1 | tee -a /tmp/claude_auth_check.txt
sleep 5
curl -s http://localhost:4000/health 2>&1 | tee -a /tmp/claude_auth_check.txt
```

### Phase 4 — Identify Services That Should Use the Proxy

Scan docker-compose.yml and service source files for hardcoded Anthropic API calls:
```zsh
grep -rn "anthropic\|openai\|ANTHROPIC_API_KEY\|api.openai.com\|api.anthropic.com" --include="*.py" --include="*.js" --include="*.ts" --include="*.env*" . 2>/dev/null | grep -v ".git" | tee -a /tmp/claude_auth_check.txt
```

For each service found, note the file and line. Do NOT modify the services in this prompt — just document them for the next prompt.

### Phase 5 — Cline Settings Documentation

Document the correct Cline settings (for manual application in VSCode since Cline settings live in the IDE, not the repo):

Write a reference doc at `docs/cline-claude-max-setup.md`:
```zsh
printf '# Cline + Claude Max Setup\n\nLast updated: %s\n\n## Cline API Configuration\n\n- API Provider: Claude Code\n- Path to claude CLI: %s\n- Model for heavy prompts: claude-opus-4-20250514\n- Model for fast prompts: claude-sonnet-4-20250514\n\n## LiteLLM Proxy\n\n- Running at: http://localhost:4000\n- Config: ops/litellm_config.yaml\n- LaunchAgent: ~/Library/LaunchAgents/ai.symphony.litellm-proxy.plist\n- Logs: /tmp/litellm_proxy.log\n\n## Services That Need Proxy Update\n\nSee ops/verification/ latest AA verification file for the full list.\n\n## Notes\n\nMax subscription active until ~May 11 2026. After that revert services\nto direct Anthropic API key. The ANTHROPIC_API_KEY in .env is the fallback.\n' "$(date '+%Y-%m-%d')" "$(which claude)" > docs/cline-claude-max-setup.md
```

### Phase 6 — Commit

```zsh
git add ops/litellm_config.yaml docs/cline-claude-max-setup.md
git add ~/Library/LaunchAgents/ai.symphony.litellm-proxy.plist 2>/dev/null || true
git commit -m "ops(AA): Claude Max wired — LiteLLM proxy + auth verification + Cline setup docs"
git push origin main
```

## Guardrails

- Do NOT print or log actual secret values — key names only
- Do NOT modify any running Docker service configs in this prompt
- Do NOT stop or restart any existing services
- Do NOT touch CLAUDE.md (that is Prompt V's job)
- If LiteLLM install fails, document it and continue — do not block on it

## Final Report

Write verification output:
```zsh
TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
REPORT="ops/verification/${TIMESTAMP}-claude-max-setup.txt"
cp /tmp/claude_auth_check.txt "$REPORT"
printf '\n--- SUMMARY ---\n' >> "$REPORT"
printf 'Claude CLI version: %s\n' "$(claude --version 2>&1)" >> "$REPORT"
printf 'LiteLLM proxy health: %s\n' "$(curl -s http://localhost:4000/health 2>&1)" >> "$REPORT"
printf 'Cline docs written: docs/cline-claude-max-setup.md\n' >> "$REPORT"
git add "$REPORT"
git commit -m "ops(AA): verification report — claude max setup"
git push origin main
```
