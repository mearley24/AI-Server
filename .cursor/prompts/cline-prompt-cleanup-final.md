# Cleanup Final — OpenWebUI Removal + CLAUDE.md + DB Consolidation + Sell Haircut

## Context
Claude Code's Z3–Z14 audit pass fixed most items. These are the remaining gaps that were never touched.

---

## Task 1: Remove OpenWebUI from docker-compose.yml

The service block and named volume are still present despite STATUS_REPORT saying it was removed.

### Steps

1. **Delete the entire `openwebui:` service block** (lines 8–21 approximately) from `docker-compose.yml`. The block starts with `  openwebui:` and ends before the next service definition.

2. **Delete the `openwebui:` named volume** from the `volumes:` section at the bottom of docker-compose.yml. Keep `redis_data:` and any other volumes.

3. **Stop and remove the running container + orphan volume:**
```zsh
docker stop openwebui 2>/dev/null; docker rm openwebui 2>/dev/null
docker volume rm ai-server_openwebui 2>/dev/null || true
```

4. **Validate compose file:**
```zsh
docker compose config --quiet && echo "compose valid" || echo "BROKEN"
```

5. **Remove the openwebui row from the CLAUDE.md service table.** Find the line:
```
| openwebui | 3000 → 8080 | — | Local LLM UI |
```
Delete it entirely.

6. **Update the container count** in CLAUDE.md. Find `19 containers` and change to `18 containers`.

### Verification
```zsh
grep -c "openwebui" docker-compose.yml
```
Expected: `0`

```zsh
grep -c "openwebui" CLAUDE.md
```
Expected: `0`

---

## Task 2: jobs.db follow_up_log Consolidation

The `follow_up_log` table was created in `jobs.db` but the code was updated to write to `follow_ups.db` instead. The `jobs.db` copy has 0 rows and is a dead table.

### Steps

1. **Confirm follow_up_log in jobs.db is empty:**
```zsh
python3 -c "
import sqlite3
conn = sqlite3.connect('data/openclaw/jobs.db')
try:
    count = conn.execute('SELECT count(*) FROM follow_up_log').fetchone()[0]
    print(f'follow_up_log rows in jobs.db: {count}')
except:
    print('Table does not exist in jobs.db')
conn.close()
"
```

2. **If the table exists and has 0 rows, drop it:**
```zsh
python3 -c "
import sqlite3
conn = sqlite3.connect('data/openclaw/jobs.db')
conn.execute('DROP TABLE IF EXISTS follow_up_log')
conn.commit()
print('Dropped follow_up_log from jobs.db')
conn.close()
"
```

3. **Confirm follow_ups.db is the canonical store:**
```zsh
python3 -c "
import sqlite3
conn = sqlite3.connect('data/openclaw/follow_ups.db')
count = conn.execute('SELECT count(*) FROM follow_ups').fetchone()[0]
print(f'follow_ups rows in follow_ups.db: {count}')
try:
    log_count = conn.execute('SELECT count(*) FROM follow_up_log').fetchone()[0]
    print(f'follow_up_log rows in follow_ups.db: {log_count}')
except:
    print('No follow_up_log table in follow_ups.db (engine creates on first send)')
conn.close()
"
```

4. **Update the CLAUDE.md database section** (if one exists) to clarify that `follow_up_log` lives in `follow_ups.db`, not `jobs.db`.

### Verification
```zsh
python3 -c "
import sqlite3
conn = sqlite3.connect('data/openclaw/jobs.db')
tables = [r[0] for r in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()]
print(f'jobs.db tables: {tables}')
assert 'follow_up_log' not in tables, 'follow_up_log still in jobs.db!'
print('PASS: follow_up_log removed from jobs.db')
"
```

---

## Task 3: Sell Haircut Rounding Audit (Lesson 17)

Lesson 17 from April 4 says: "Sell haircut rounding causes exit loops — the bot tries to sell, the amount rounds to the same value, and it loops."

### Steps

1. **Search for all sell/exit logic in polymarket-bot:**
```zsh
grep -rn "sell\|exit_position\|close_position\|_execute_sell\|_do_sell" polymarket-bot/src/ polymarket-bot/strategies/ --include="*.py" | grep -v ".pyc"
```

2. **For each sell function found, check:**
   - Does it round the sell amount? (Look for `round()`, `int()`, `math.floor()`, `math.ceil()`)
   - After rounding, could the sell amount equal the current position size, causing a no-op loop?
   - Is there a minimum sell amount check (e.g., skip if sell amount < 1 share)?

3. **If any sell function lacks loop protection, add it:**
```python
# Before any sell order:
if shares_to_sell < 1:
    log.info("sell_skip_dust", shares=shares_to_sell, reason="below_minimum")
    return  # or break out of the loop
```

4. **Also check that rounding uses consistent direction:**
   - Buy amounts should round DOWN (never overspend)
   - Sell amounts should round DOWN (never try to sell more than held)

5. **Document findings.** If the code already handles this correctly, add a comment:
```python
# Lesson 17: sell amounts round DOWN to prevent exit loops.
```

### Verification
```zsh
grep -rn "Lesson 17\|exit.loop\|sell_skip_dust\|below_minimum" polymarket-bot/ --include="*.py"
```
Should show at least one reference confirming the issue is addressed.

---

## Commit

Commit all changes with:
```
git add -A
git commit -m "cleanup: remove openwebui, drop dead follow_up_log table, audit sell haircut rounding"
```

Push with:
```
git push origin main
```
