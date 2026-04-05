#!/usr/bin/env bash
# =============================================================================
# fix-redeemer-and-dust.sh
# Fixes: nonce race condition, adds dust sweeper, auto-cleanup of old positions
# Run from AI-Server repo root:  bash fix-redeemer-and-dust.sh
# =============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)"
cd "$REPO_DIR"

echo "========================================"
echo "Fix: Redeemer Nonce + Dust Sweeper"
echo "$(date)"
echo "========================================"

# ------------------------------------------------------------------
# 1. Backup
# ------------------------------------------------------------------
TS=$(date +%Y%m%d_%H%M%S)
mkdir -p .backups/$TS
cp polymarket-bot/src/redeemer.py .backups/$TS/
cp polymarket-bot/strategies/polymarket_copytrade.py .backups/$TS/
echo "[1/4] Backups saved"

# ------------------------------------------------------------------
# 2. Fix nonce race condition in redeemer
# ------------------------------------------------------------------
echo "[2/4] Fixing redeemer nonce handling..."

python3 << 'FIX_NONCE'
path = "polymarket-bot/src/redeemer.py"
with open(path, "r") as f:
    content = f.read()

# Add a nonce tracker to __init__
old_init_end = '        # Track already-redeemed condition IDs to avoid redundant txns\n        self._redeemed_conditions: set[str] = set()'
new_init_end = '''        # Track already-redeemed condition IDs to avoid redundant txns
        self._redeemed_conditions: set[str] = set()

        # Nonce tracker — avoids race conditions when sending multiple txns
        self._next_nonce: Optional[int] = None'''

if old_init_end in content:
    content = content.replace(old_init_end, new_init_end)
    print("  Added nonce tracker to __init__")

# Replace the nonce fetch inside _redeem_single to use tracked nonce
old_nonce = '            nonce = self._w3.eth.get_transaction_count(self._wallet_address)'
new_nonce = '''            # Use tracked nonce to avoid race conditions between rapid txns
            if self._next_nonce is not None:
                nonce = self._next_nonce
            else:
                nonce = self._w3.eth.get_transaction_count(self._wallet_address)'''

if old_nonce in content:
    content = content.replace(old_nonce, new_nonce)
    print("  Fixed nonce fetch to use tracker")

# After successful receipt, increment nonce
old_receipt = '''            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt.status != 1:
                raise RuntimeError(f"Transaction reverted: {tx_hash_hex}")

            return tx_hash_hex'''
new_receipt = '''            receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            if receipt.status != 1:
                self._next_nonce = None  # Reset on failure
                raise RuntimeError(f"Transaction reverted: {tx_hash_hex}")

            # Increment tracked nonce for next txn
            self._next_nonce = nonce + 1
            return tx_hash_hex'''

if old_receipt in content:
    content = content.replace(old_receipt, new_receipt)
    print("  Added nonce increment on success")

# Reset nonce at start of each redeem_all_winning cycle
old_gas_check = '        # 1. Check gas price'
new_gas_check = '''        # Reset nonce tracker at start of each cycle
        self._next_nonce = None

        # 1. Check gas price'''

if old_gas_check in content:
    content = content.replace(old_gas_check, new_gas_check, 1)
    print("  Added nonce reset at cycle start")

# Also reset nonce on error in the redeem loop
old_error_block = '''                errors.append({"condition_id": condition_id[:20], "error": err_msg[:80]})'''
new_error_block = '''                self._next_nonce = None  # Reset nonce on error to re-fetch
                errors.append({"condition_id": condition_id[:20], "error": err_msg[:80]})'''

if old_error_block in content:
    content = content.replace(old_error_block, new_error_block)
    print("  Added nonce reset on error")

with open(path, "w") as f:
    f.write(content)
print("  redeemer.py updated")
FIX_NONCE

# ------------------------------------------------------------------
# 3. Add dust sweeper + auto-cleanup to copytrade strategy
# ------------------------------------------------------------------
echo "[3/4] Adding dust sweeper and position auto-cleanup..."

python3 << 'FIX_DUST'
path = "polymarket-bot/strategies/polymarket_copytrade.py"
with open(path, "r") as f:
    content = f.read()

# Find the force_stale_cleanup block and add dust sweeper logic right after it
# We'll add a dust check that fires during the position evaluation loop

# Add DUST_THRESHOLD constant near the top of the file after existing constants
# Find a good spot — after CATEGORY_EXIT_PARAMS or similar
import re

# Add dust threshold constant
if "DUST_VALUE_THRESHOLD" not in content:
    # Find where CATEGORY_EXIT_PARAMS is defined and add after its closing brace
    cat_params_match = re.search(r'(CATEGORY_EXIT_PARAMS\s*=\s*\{[^}]+(?:\{[^}]*\}[^}]*)*\})', content, re.DOTALL)
    if cat_params_match:
        insert_pos = cat_params_match.end()
        dust_constant = '''

# Positions below this estimated USD value are considered dust and will be force-sold
DUST_VALUE_THRESHOLD = 1.00

# Positions held longer than this (hours) with value under $2 are stale dust
STALE_DUST_HOURS = 24
'''
        content = content[:insert_pos] + dust_constant + content[insert_pos:]
        print("  Added DUST_VALUE_THRESHOLD and STALE_DUST_HOURS constants")
    else:
        print("  WARNING: Could not find CATEGORY_EXIT_PARAMS to insert constants")

# Add dust sweep logic into the position evaluation loop
# Insert after the force_stale_cleanup block
old_stale_cleanup_end = '''                        exits_to_execute.append((pos_id, ExitSignal(
                            position_id=pos_id,
                            reason="force_stale_cleanup",
                            sell_fraction=1.0,
                            current_price=current_price,
                            entry_price=pos.entry_price,
                            pnl_pct=(current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
                            hold_time_hours=hold_hours,
                        )))'''

new_stale_cleanup_end = '''                        exits_to_execute.append((pos_id, ExitSignal(
                            position_id=pos_id,
                            reason="force_stale_cleanup",
                            sell_fraction=1.0,
                            current_price=current_price,
                            entry_price=pos.entry_price,
                            pnl_pct=(current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
                            hold_time_hours=hold_hours,
                        )))

                # Dust sweeper: sell positions worth less than $1, or under $2 and held >24h
                if not signal and pos_id not in [e[0] for e in exits_to_execute]:
                    est_value = current_price * pos.size_shares if hasattr(pos, 'size_shares') else 0
                    hold_hours_dust = (time.time() - pos.copied_at) / 3600
                    is_dust = est_value < DUST_VALUE_THRESHOLD
                    is_stale_dust = est_value < 2.0 and hold_hours_dust > STALE_DUST_HOURS

                    if is_dust or is_stale_dust:
                        reason = "dust_sweep" if is_dust else "stale_dust_sweep"
                        logger.info(
                            "copytrade_dust_sweep",
                            position_id=pos_id,
                            market=pos.market_question[:50],
                            est_value=round(est_value, 2),
                            hold_hours=round(hold_hours_dust, 1),
                            reason=reason,
                        )
                        exits_to_execute.append((pos_id, ExitSignal(
                            position_id=pos_id,
                            reason=reason,
                            sell_fraction=1.0,
                            current_price=current_price,
                            entry_price=pos.entry_price,
                            pnl_pct=(current_price - pos.entry_price) / pos.entry_price if pos.entry_price > 0 else 0,
                            hold_time_hours=hold_hours_dust,
                        )))'''

if old_stale_cleanup_end in content:
    content = content.replace(old_stale_cleanup_end, new_stale_cleanup_end)
    print("  Added dust sweeper to position evaluation loop")
else:
    print("  WARNING: Could not find force_stale_cleanup block for dust sweeper insertion")

# Also handle the _exit_position method — for dust_sweep and stale_dust_sweep,
# if the sell fails (e.g., no liquidity), just remove from tracking
# Find the resolved cleanup section in _exit_position
old_resolved_check = '                    if signal.reason in ("market_resolved", "force_stale_cleanup"):'
new_resolved_check = '                    if signal.reason in ("market_resolved", "force_stale_cleanup", "dust_sweep", "stale_dust_sweep"):'

if old_resolved_check in content:
    content = content.replace(old_resolved_check, new_resolved_check)
    print("  Added dust_sweep to cleanup-on-fail reasons")

# Add dust_sweep to the reason label map
old_label_map_end = '            "force_stale_cleanup": "Force Cleaned",'
new_label_map_end = '''            "force_stale_cleanup": "Force Cleaned",
            "dust_sweep": "Dust Swept",
            "stale_dust_sweep": "Stale Dust Swept",'''

if old_label_map_end in content:
    content = content.replace(old_label_map_end, new_label_map_end)
    print("  Added dust sweep labels")

with open(path, "w") as f:
    f.write(content)
print("  polymarket_copytrade.py updated")
FIX_DUST

# ------------------------------------------------------------------
# 4. Rebuild and restart
# ------------------------------------------------------------------
echo "[4/4] Rebuilding polymarket-bot..."

docker compose build --no-cache polymarket-bot 2>&1 | tail -3
docker compose up -d polymarket-bot 2>&1 | tail -3

echo ""
echo "========================================"
echo "DONE. Waiting 30s for startup..."
echo "========================================"

sleep 30

echo ""
echo "--- Dust sweep activity ---"
docker logs polymarket-bot --tail 50 2>&1 | grep -i "dust_sweep\|dust" | tail -10 || echo "  No dust sweeps yet (next tick)"

echo ""
echo "--- Redeemer status ---"
docker logs polymarket-bot --tail 50 2>&1 | grep -i "redeemer" | tail -5

echo ""
echo "--- Any errors ---"
docker logs polymarket-bot --tail 50 2>&1 | grep -i "error" | grep -v "health" | tail -5 || echo "  None"

echo ""
echo "========================================"
echo "Dust sweeper will sell positions under \$1 on next tick."
echo "Positions under \$2 held >24h also swept."
echo "Redeemer nonce race condition fixed."
echo "========================================"
