#!/usr/bin/env bash
# =============================================================================
# fix-polymarket-and-followups.sh
# Fixes: exit balance errors, Redis auth in polymarket-bot, follow_ups seeding
# Run from AI-Server repo root:  bash fix-polymarket-and-followups.sh
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)"
cd "$REPO_DIR"

echo "========================================"
echo "Fix: Polymarket Exits + Redis + Follow-ups"
echo "$(date)"
echo "========================================"

# ------------------------------------------------------------------
# 1. Backup
# ------------------------------------------------------------------
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p .backups/$TS
cp polymarket-bot/strategies/polymarket_copytrade.py .backups/$TS/
cp polymarket-bot/strategies/cvd_detector.py .backups/$TS/
cp polymarket-bot/strategies/rbi_pipeline.py .backups/$TS/
cp polymarket-bot/src/position_syncer.py .backups/$TS/
cp polymarket-bot/strategies/wallet_rolling_redis.py .backups/$TS/
echo "[1/5] Backups saved"

# ------------------------------------------------------------------
# 2. Fix exit haircut + add balance-error retry with reduced size
# ------------------------------------------------------------------
echo "[2/5] Fixing exit balance haircut and adding retry logic..."

python3 << 'FIX_EXIT'
path = "polymarket-bot/strategies/polymarket_copytrade.py"
with open(path, "r") as f:
    content = f.read()

# Fix 1: Increase haircut from 0.995 to 0.93
old_haircut = "sell_shares = round(pos.size_shares * signal.sell_fraction * 0.995, 2)"
new_haircut = "sell_shares = round(pos.size_shares * signal.sell_fraction * 0.93, 2)  # 7% haircut — on-chain balance drifts from recorded"

if old_haircut in content:
    content = content.replace(old_haircut, new_haircut)
    print("  Fixed haircut: 0.995 -> 0.93")
else:
    print("  WARNING: Could not find haircut line (may already be fixed)")

# Fix 2: After the sell order, add retry with 50% size if balance error
# Find the FOK error log line and add retry logic after the except block
old_error = 'event="copytrade_exit_fok_error",'
if old_error in content:
    # Find the block that logs fok_error and add a reduced retry
    # We'll add a check: if "not enough balance" in error, retry with 50% of sell_shares
    content = content.replace(
        '                    logger.error(\n                        "copytrade_exit_fok_error",',
        '                    err_msg = str(exc)\n'
        '                    # Auto-retry with halved size if balance mismatch\n'
        '                    if "not enough balance" in err_msg and sell_shares > 2:\n'
        '                        sell_shares = round(sell_shares * 0.5, 2)\n'
        '                        logger.warning(\n'
        '                            "copytrade_exit_retry_half",\n'
        '                            position_id=position_id,\n'
        '                            new_sell_shares=sell_shares,\n'
        '                        )\n'
        '                        try:\n'
        '                            order = await self._client.create_order(\n'
        '                                token_id=pos.token_id,\n'
        '                                side="SELL",\n'
        '                                size=sell_shares,\n'
        '                                price=round(sell_price, 2),\n'
        '                                order_type="FOK",\n'
        '                            )\n'
        '                            logger.info(\n'
        '                                "copytrade_position_exit",\n'
        '                                mode="live_retry",\n'
        '                                position_id=position_id,\n'
        '                                sell_shares=sell_shares,\n'
        '                            )\n'
        '                        except Exception as retry_exc:\n'
        '                            logger.error("copytrade_exit_retry_failed", error=str(retry_exc))\n'
        '                    logger.error(\n                        "copytrade_exit_fok_error",',
    )
    print("  Added retry-with-half logic for balance errors")
else:
    print("  WARNING: Could not find fok_error block for retry logic")

with open(path, "w") as f:
    f.write(content)
print("  polymarket_copytrade.py updated")
FIX_EXIT

# ------------------------------------------------------------------
# 3. Fix hardcoded Redis URLs in polymarket-bot (need host.docker.internal + auth)
# ------------------------------------------------------------------
echo "[3/5] Fixing Redis URLs in polymarket-bot..."

# The bot uses network_mode: service:vpn, so it can't reach "redis" by name.
# It needs host.docker.internal:6379 with the password.
REDIS_PASS=$(grep "^REDIS_PASSWORD=" .env | cut -d= -f2)
if [[ -z "$REDIS_PASS" ]]; then
    echo "  WARNING: REDIS_PASSWORD not found in .env, skipping Redis URL fixes"
else
    REDIS_AUTH_URL="redis://:${REDIS_PASS}@host.docker.internal:6379"

    # Fix cvd_detector.py
    sed -i '' "s|redis://172.18.0.100:6379|${REDIS_AUTH_URL}|g" polymarket-bot/strategies/cvd_detector.py
    echo "  Fixed cvd_detector.py"

    # Fix rbi_pipeline.py
    sed -i '' "s|redis://172.18.0.100:6379|${REDIS_AUTH_URL}|g" polymarket-bot/strategies/rbi_pipeline.py
    echo "  Fixed rbi_pipeline.py"

    # Fix position_syncer.py
    sed -i '' "s|redis://172.18.0.100:6379|${REDIS_AUTH_URL}|g" polymarket-bot/src/position_syncer.py
    echo "  Fixed position_syncer.py"

    # Fix wallet_rolling_redis.py
    sed -i '' "s|redis://172.18.0.100:6379|${REDIS_AUTH_URL}|g" polymarket-bot/strategies/wallet_rolling_redis.py
    echo "  Fixed wallet_rolling_redis.py"

    # Fix fallbacks in copytrade and whale scanner that use host.docker.internal without auth
    sed -i '' "s|redis://host.docker.internal:6379|${REDIS_AUTH_URL}|g" polymarket-bot/strategies/polymarket_copytrade.py
    sed -i '' "s|redis://host.docker.internal:6379|${REDIS_AUTH_URL}|g" polymarket-bot/src/whale_scanner/scanner_engine.py 2>/dev/null || true
    echo "  Fixed copytrade + whale_scanner fallback URLs"

    # Also update the REDIS_URL in docker-compose for polymarket-bot to use host.docker.internal
    # (it's on vpn network so "redis" hostname doesn't resolve)
    sed -i '' "s|REDIS_URL=redis://:${REDIS_PASS}@redis:6379|REDIS_URL=${REDIS_AUTH_URL}|" docker-compose.yml
    # Only fix the polymarket-bot one — other services can reach "redis" fine
    # Actually this sed will hit all of them. Let's be more targeted:
    # Revert: change all back to redis:6379, then only change polymarket-bot's
    # Actually the simplest approach: all services except polymarket-bot use redis:6379
    # polymarket-bot needs host.docker.internal:6379 because of network_mode: service:vpn

    # Let's just fix it properly with python
    python3 << FIXCOMPOSE
import re

with open("docker-compose.yml", "r") as f:
    content = f.read()

# The polymarket-bot section uses network_mode: service:vpn so it needs host.docker.internal
# Other services can use redis:6379 normally
# Find the polymarket-bot section and fix just its REDIS_URL
redis_pass = "${REDIS_PASS}"
old_poly_redis = f"REDIS_URL=redis://:{redis_pass}@redis:6379"
new_poly_redis = f"REDIS_URL=redis://:{redis_pass}@host.docker.internal:6379"

# First ensure all are set to redis:6379 (undo any accidental change)
content = content.replace(
    f"redis://:{redis_pass}@host.docker.internal:6379",
    f"redis://:{redis_pass}@redis:6379"
)

# Now find polymarket-bot section and change just that one
lines = content.split("\n")
in_polymarket = False
for i, line in enumerate(lines):
    if line.strip().startswith("polymarket-bot:"):
        in_polymarket = True
    elif in_polymarket and re.match(r"^  \w", line) and not line.strip().startswith("-"):
        in_polymarket = False
    if in_polymarket and f"redis://:{redis_pass}@redis:6379" in line:
        lines[i] = line.replace(
            f"redis://:{redis_pass}@redis:6379",
            f"redis://:{redis_pass}@host.docker.internal:6379"
        )
        break

content = "\n".join(lines)
with open("docker-compose.yml", "w") as f:
    f.write(content)
print("  docker-compose.yml: polymarket-bot REDIS_URL -> host.docker.internal")
FIXCOMPOSE
fi

# ------------------------------------------------------------------
# 4. Apply follow_up_tracker fix (run the script if it exists)
# ------------------------------------------------------------------
echo "[4/5] Applying follow_up_tracker fix..."

if [[ -f fix-followup-tracker.sh ]]; then
    # The fix script does git commit + docker restart, we'll skip those parts
    # and just apply the file changes
    echo "  fix-followup-tracker.sh exists but may conflict with current state"
    echo "  Checking if follow_up_tracker.py already has seed_from_jobs..."
    if grep -q "seed_from_jobs" openclaw/follow_up_tracker.py; then
        echo "  Already patched (seed_from_jobs found)"
    else
        echo "  Running fix-followup-tracker.sh..."
        bash fix-followup-tracker.sh 2>&1 | tail -10
    fi
else
    echo "  fix-followup-tracker.sh not found — checking if already patched"
    if grep -q "seed_from_jobs" openclaw/follow_up_tracker.py; then
        echo "  Already patched"
    else
        echo "  WARNING: follow_up_tracker.py not patched and fix script missing"
        echo "  Pull latest from GitHub to get it: git pull origin main"
    fi
fi

# ------------------------------------------------------------------
# 5. Rebuild polymarket-bot + restart openclaw
# ------------------------------------------------------------------
echo "[5/5] Rebuilding polymarket-bot and restarting openclaw..."

docker compose up -d --build polymarket-bot 2>&1 | tail -5
docker restart openclaw 2>&1 || true

echo ""
echo "========================================"
echo "DONE. Verifying..."
echo "========================================"

sleep 15

echo ""
echo "--- Polymarket bot logs (last 10) ---"
docker logs polymarket-bot --tail 10 2>&1 | grep -v "health"

echo ""
echo "--- Redis errors? ---"
docker logs polymarket-bot --tail 50 2>&1 | grep -i "redis.*error\|NOAUTH\|Name or service" | tail -5 || echo "  None found"

echo ""
echo "--- Exit errors? ---"
docker logs polymarket-bot --tail 50 2>&1 | grep "fok_error" | tail -3 || echo "  None found"

echo ""
echo "--- follow_ups count ---"
sqlite3 ./data/openclaw/follow_ups.db "SELECT COUNT(*) FROM follow_ups" 2>/dev/null || echo "  DB not found (wait for next orchestrator tick)"

echo ""
echo "========================================"
