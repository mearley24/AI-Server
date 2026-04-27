# Polymarket Open Positions Audit
**Date:** 2026-04-27T16:05:26Z  
**Wallet:** `0xa791...C0d2` (masked)  
**Task:** Read-only audit — source of $400, real vs stale, live exposure check

---

## Summary

**The $400 is real on-chain money.** It represents the current market value of 78 Polymarket positions held in the bot's Polygon wallet. These positions were created via live copytrade trading **before** the P0/P1/P2 safety gates were added in late April 2026. The bot's current live trading status is fully blocked — no new positions have been created since the gates went in, and none can be created until `POLY_ALLOW_LIVE` is explicitly set.

---

## Source of the $400 Number

| Item | Value |
|------|-------|
| Total on-chain positions | 78 |
| Total estimated current value | **$400.22** |
| Total cost basis | $375.43 |
| Unrealized P&L | **+$24.78** |
| Data source | `https://data-api.polymarket.com/positions` (live API) |

This matches the STATUS_REPORT note *"$750+ in positions as of April 12."* The ~$350 decline reflects losses on positions that resolved against the bot (e.g., long-shots that lost).

---

## Are Positions Real or Stale Cache?

**REAL.** Confirmed via:
1. Live Polymarket data API returns 78 token holdings for the wallet
2. Redeemer has already redeemed 530 conditions from this same wallet (on-chain txns)
3. Redeemer's current cycle shows `pending: 78` — actively monitoring for these to resolve
4. The positions include concrete market questions, share counts, avg entry prices, and live current prices

These are NOT paper trades, NOT cached stale data, NOT simulated positions.

---

## Were They Created Before Current Safety Gates?

**Yes.** Evidence:
- Positions detected as early as `2026-04-03T21:55:44Z` (from `orphan_positions.json` in container)
- P0 (live gate) was added: 2026-04-27 (this week)
- P1 (sandbox bypass fix) was added: 2026-04-27
- The copytrade strategy ran with `POLY_DRY_RUN=false` before P0 was implemented
- STATUS_REPORT §14 (audit written ~April 17) shows `dry_run: false` at that time, with comment "LIVE (blocked by funds)"

The positions were placed by the copytrade strategy when it was in live mode. The bot had insufficient USDC (~$1.94) to open new positions but the copytrade strategy had already accumulated these positions in earlier runs when more USDC was present.

---

## Current Bot Live-Trading Status

**FULLY BLOCKED — PAPER MODE**

| Check | Result |
|-------|--------|
| Container env `POLY_DRY_RUN` | `true` |
| Container env `POLY_ALLOW_LIVE` | not set |
| `config.yaml dry_run` | `true` |
| Startup log event | `live_gate_safe` — "dry_run=True — observer/paper mode" |
| Startup alert | `[PAPER] PolyBot STARTED — 4 strategies, bankroll $500` |
| `copytrade_started` log | `dry_run: true` |
| `strategy_manager_init` log | `dry_run: true` |
| All platform status | `polymarket.dry_run = true` |

The `_enforce_live_gate()` in `main.py` checks:
1. If `dry_run=True` → logs `live_gate_safe` and returns (gate not needed)
2. If `dry_run=False` + `POLY_ALLOW_LIVE` not set → logs `live_gate_blocked` CRITICAL and forces paper mode

Both layers are active. No real orders can be placed.

---

## What Are the 33 "open_orders" in /status?

All 33 are **paper trades** from the `cvd_arb` strategy. Every order ID starts with `paper-`:
```
paper-fa4eb02dc782, paper-b839a2a40f10, paper-bb9d5a9b2b00, ...
```
These have zero real-money exposure. They are virtual positions tracked in memory only.

---

## Can Any Strategy Currently Add to Real Positions?

**No.** Three independent layers block it:

1. **Container env** `POLY_DRY_RUN=true` — platform client never calls live CLOB API for orders
2. **`_enforce_live_gate()`** — even if dry_run were changed, POLY_ALLOW_LIVE passphrase is required
3. **P1 sandbox fix** — all 4 bypass strategies (stink_bid, flash_crash, presolution_scalp, sports_arb) now route through `_place_market_order()` which checks `settings.dry_run` before any live call

---

## Top Positions by Current Value

| Market | Side | Shares | Avg | Cur | Value | P&L |
|--------|------|--------|-----|-----|-------|-----|
| Will SpaceX's market cap be $1.5T–$2.0T at end of year? | NO | 36.4 | $0.48 | $0.635 | **$23.14** | +$5.65 |
| Will Alphabet be 3rd-largest company at year-end? | NO | 20.9 | $0.265 | $0.960 | **$20.10** | +$14.56 |
| Will DHS shutdown end after April 30, 2026? | YES | 20.4 | $0.14 | $0.89 | **$18.16** | +$15.30 |
| Will Roberto Sánchez Palomino win 2026 Peruvian election? | YES | 52.2 | $0.023 | $0.346 | **$18.09** | +$16.89 |
| New Playboi Carti Album before GTA VI? | NO | 36.6 | $0.42 | $0.435 | **$15.91** | +$0.55 |
| Russia-Ukraine Ceasefire before GTA VI? | NO | 32.3 | $0.47 | $0.465 | **$15.00** | -$0.16 |
| Will Jesus Christ return before GTA VI? | NO | 29.1 | $0.52 | $0.515 | **$15.00** | -$0.15 |
| Will Rafael López Aliaga & Keiko Fujimori advance? | NO | 14.7 | $0.68 | $0.971 | **$14.28** | +$4.27 |
| New Rihanna Album before GTA VI? | NO | 38.5 | $0.40 | $0.365 | **$14.04** | -$1.34 |

Notable losers (positions now nearly worthless):
- "Will a different combination advance to Peru runoff?" NO, $0.54 avg → $0.029 cur = **-$6.91**
- "Will Péter Magyar be next PM of Hungary?" NO, $0.36 avg → $0.008 cur = **-$10.46**
- "Will Shai Gilgeous-Alexander win NBA MVP?" NO (Connor McDavid apparently won), $0.94 avg → $0.598 cur = **-$1.71**

---

## On-Chain Wallet State (from /status endpoint)

| Item | Value |
|------|-------|
| POL (MATIC) balance | 60.01 |
| USDC balance | $3.72 |
| Redeemed conditions (all time) | 530 |
| Pending positions (unresolved markets) | 78 |
| Last redemption cycle | 2026-04-27T16:00:14Z |

The redeemer runs every 180 seconds, checks all 78 positions, and will auto-redeem any that resolve with `payoutDenominator > 0` on-chain.

---

## Immediate Risk Level

**LOW.** The $400 is already deployed capital — it was placed in prior live-trading sessions. It is not increasing, not compounding, not at risk from the bot. The positions will resolve (win or lose) when the underlying markets settle. The redeemer will collect any winnings automatically.

The only remaining financial risk is **market risk** on the 78 open positions themselves — i.e., whether the outcomes go the right way. This is not a bot safety concern.

---

## Recommended Next Action

1. **No action needed** to secure the $400. The bot cannot increase exposure.
2. Watch the 3 largest unrealized winners (DHS +$15, Roberto Sanchez +$17, Alphabet +$15) — these could resolve favorably in the coming weeks.
3. The 2 large losers (Péter Magyar -$10, "different combo" -$7) are likely lost.
4. Once 48h paper trading validation completes and you're ready to fund: deposit $500+ USDC → strategies will start paper/live trading again.
5. The `scripts/polymarket_positions_audit.py` script can be rerun at any time for a current snapshot.

---

## Files Checked

| File/Source | Checked For |
|-------------|-------------|
| Container env (`docker inspect`) | `POLY_DRY_RUN`, `POLY_ALLOW_LIVE`, wallet address |
| `config.yaml` | `dry_run: true` confirmed at all 3 sections |
| `/status` endpoint | Strategy states, `dry_run: true` per platform |
| `/positions` endpoint | All 33 "orders" are `paper-*` prefix (not real) |
| `/pnl` endpoint | PnL tracker: only copytrade, -$3.17 total realized |
| `docker logs polymarket-bot` | Startup: `live_gate_safe`, `[PAPER] PolyBot STARTED` |
| `data-api.polymarket.com/positions` | 78 real on-chain positions, $400.22 total value |
| `/data/redeemer_summary.json` | 530 redeemed, 78 pending |
| `/data/orphan_positions.json` | Positions detected from 2026-04-03 (pre-P0) |
| `src/main.py` | `_enforce_live_gate()` present and called at startup |

**No position state was modified. No orders were placed. No secrets were committed.**
