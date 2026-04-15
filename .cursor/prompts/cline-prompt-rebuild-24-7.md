## Rebuild & Verify 24/7 Services

You are working on ~/AI-Server on Bob.

### Goal

Pull latest fixes, rebuild affected containers, verify all three revenue-generating systems are actually working: Cortex autobuilder scanning, Kraken market maker, and Perplexity research pipeline.

### Step 1 — Pull and rebuild

```zsh
bash scripts/pull.sh
docker compose build cortex cortex-autobuilder polymarket-bot openclaw x-intake x-intake-lab
docker compose up -d --no-deps cortex cortex-autobuilder polymarket-bot openclaw x-intake x-intake-lab
```

Wait 30 seconds for services to stabilize.

### Step 2 — Verify Cortex Autobuilder is scanning

```zsh
docker logs cortex-autobuilder --tail 50 --since 2m
```

**Expected**: You should see `scanner_querying topic=...` lines, NOT `scanner_no_perplexity_key` or `scanner_ollama_error` dominating every cycle. If you see Perplexity queries succeeding and Ollama processing (or OpenAI fallback), the scanner is working.

If you see `scanner_no_perplexity_key`:
- Run `docker exec cortex-autobuilder printenv PERPLEXITY_API_KEY` — if empty, check `.env` has `PERPLEXITY_API_KEY=pplx-...`
- Rebuild: `docker compose up -d --no-deps cortex-autobuilder`

If you see `scanner_ollama_error` followed by `scanner_openai_fallback_error`:
- Ollama on Maestro (192.168.1.199:11434) is unreachable AND OpenAI key is missing
- Run `docker exec cortex-autobuilder printenv OPENAI_API_KEY` — if empty, check `.env` has `OPENAI_API_KEY=sk-...`
- Test Maestro connectivity: `curl -s http://192.168.1.199:11434/api/tags | head -5`

### Step 3 — Verify Kraken market maker

```zsh
docker logs polymarket-bot --tail 50 --since 2m 2>&1 | grep -i "kraken\|padding\|auth\|tick\|order"
```

**Expected**: You should see tick cycles for XRP/USD, NOT `Incorrect padding` errors. The base64 padding fix auto-corrects malformed secrets.

If `Incorrect padding` still appears:
- The secret itself may be completely wrong (not just missing padding). Verify:
  ```zsh
  python3 -c "
  import base64, os
  s = os.environ.get('KRAKEN_SECRET', '')
  print(f'Length: {len(s)}, mod4: {len(s) % 4}')
  try:
      base64.b64decode(s)
      print('VALID base64')
  except Exception as e:
      print(f'INVALID: {e}')
  "
  ```
- If INVALID, the key needs to be re-copied from Kraken Pro settings.

### Step 4 — Verify Cortex is receiving memories

```zsh
curl -s http://127.0.0.1:8102/stats 2>/dev/null | python3 -m json.tool
```

Check that `total_memories` is increasing. Wait 5 minutes and check again — it should have gone up from scanner activity.

### Step 5 — Verify all containers healthy

```zsh
docker compose ps --format "table {{.Name}}\t{{.Status}}" | sort
```

All containers should show `Up` with `(healthy)` where applicable. Report any that are restarting or unhealthy.

### Step 6 — Quick Perplexity API balance sanity check

```zsh
docker logs cortex-autobuilder --tail 100 --since 5m 2>&1 | grep -c "scanner_querying"
```

If this returns a number > 0, the scanner is actively burning Perplexity credits (good). Each query costs roughly $0.005 so even running 24/7, the $98 balance will last months.

### Output

Report:
- How many scanner queries succeeded in the last 5 minutes
- Whether Ollama or OpenAI fallback is handling processing
- Whether Kraken auth is working (tick cycles visible, no padding errors)
- Current Cortex memory count
- Any containers not healthy

Commit and push any additional fixes needed:
```zsh
git add -A && git commit -m "fix: post-rebuild adjustments" && git push
```
