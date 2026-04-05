# Agent Learnings — Auto-Updated Trading Knowledge

> **Last updated: 2026-03-29 from COMPLETE activity history (597 activities, 206 unique markets)**
> **True account P/L: -$229.54 (deposited $386.49, have $156.95 in open positions)**

## Real Performance (206 markets, not cherry-picked)

### By Category (resolved only)
| Category | W | L | WR% | Won | Lost | Net | Verdict |
|---|---|---|---|---|---|---|---|
| crypto_updown | 45 | 15 | 75% | +$97 | -$41 | **+$57** | Best earner — but ONLY after both-sides fix |
| esports | 5 | 2 | 71% | +$41 | -$14 | **+$28** | Big swings — winners are huge |
| tennis | 6 | 2 | 75% | +$30 | -$12 | **+$18** | Consistent edge from copied wallets |
| weather | 9 | 12 | 43% | +$27 | -$22 | **+$4** | Barely positive — exact temps are hard |
| politics | 1 | 3 | 25% | +$3 | -$1 | **+$2** | Too small a sample, 4 more still open |
| f1 | 2 | 0 | 100% | +$0.36 | $0 | **+$0.36** | Tiny profits |
| entertainment | 1 | 2 | 33% | +$4 | -$4 | **+$0.17** | Break even |
| soccer_intl | 2 | 3 | 40% | +$7 | -$15 | **-$8** | Avoid. Unpredictable outcomes |
| us_sports | 4 | 6 | 40% | +$4 | -$19 | **-$15** | Avoid. Close matchups = coin flips |

### By Entry Price (CRITICAL INSIGHT)
| Entry Price | W | L | WR% | Action |
|---|---|---|---|---|
| >80¢ (high conviction) | 25 | 5 | **83%** | BUY MORE — best win rate |
| 40-80¢ (medium) | 44 | 28 | **61%** | Selective — need strong wallet signal |
| <40¢ (longshots) | 7 | 13 | **35%** | AVOID — lose more often than win |

### By Position Size
| Size | W | L | WR% | Net | Action |
|---|---|---|---|---|---|
| <$5 (small) | 50 | 14 | **78%** | +$63 | Keep — best risk/reward |
| $5-10 (medium) | 15 | 20 | **43%** | -$4 | REDUCE — losing money |
| $10-20 (large) | 10 | 10 | **50%** | +$35 | Only on highest conviction |
| >$20 (XL) | 1 | 2 | **33%** | -$4 | NEVER — too much risk |

### By Time of Day (MDT)
| Time | WR% | Note |
|---|---|---|
| Midnight (0:00) | **29%** | WORST — stop trading at midnight |
| 7pm (19:00) | **47%** | Below average — late night copies are weak |
| 1-4am | **88%** | Best — fewer markets, higher quality signals |
| 3-6pm | **70%** | Good — active market hours |

## The 5 Rules That Would Have Saved $100+

### Rule 1: NEVER buy both sides of the same event
**Cost: ~$50+ lost on day 1.** 20 events had multiple outcome buys (Up AND Down, both CS teams, etc). The opposite-side detection was added but ONLY for condition IDs — need to also check event slugs.
**Fix:** Block at event slug level, not just condition ID.

### Rule 2: Keep positions SMALL ($3-5 max default)
**The data is clear:** <$5 positions have 78% WR and +$63 net. Medium positions ($5-10) have 43% WR and lose money. Large positions burn capital.
**Fix:** Default position size = $3. Only scale to $5 for >80% WR wallets. Only scale to $10 for >90% WR wallets with >30 resolved.

### Rule 3: Don't enter below 40¢
**Below 40¢ entry price = 35% win rate.** These longshot bets look attractive but lose 2 out of 3 times. The winners don't pay enough to cover the losses.
**Fix:** Minimum entry price 0.40 (raise from current 0.10). Exception: crypto dip-to markets where METAR-style data gives edge.

### Rule 4: Stop trading at midnight MDT
**0:00 MDT has 29% win rate** — worst time slot. Late-night copies come from overseas wallets trading thin markets.
**Fix:** Suppress new buys between 11pm-5am MDT. Let existing positions ride.

### Rule 5: Avoid US sports and international soccer
**US sports: 40% WR, -$15 net. Soccer: 40% WR, -$8 net.** Close matchups (NBA spreads, NHL games, soccer friendlies) are coin flips. The wallets we copy don't have real edge here.
**Fix:** Set us_sports multiplier to 0.3x, soccer_intl to 0.2x. Only enter if wallet WR >85% in that specific category.

## What Actually Works
1. **Crypto up/down (post-fix):** 75% WR, +$57. Keep the both-sides guard, keep the position sizing small.
2. **Esports (CS2/Valorant):** 71% WR, +$28. The copied wallets genuinely know matchups. Keep but watch liquidity.
3. **Tennis:** 75% WR, +$18. Specific wallets (@tradecraft style) have real tennis knowledge. Trust them.
4. **Weather with METAR:** Works when we have aviation data. Dallas and Shanghai wins prove it.
5. **High entry price (>80¢):** 83% WR. When the market already agrees something will happen, the remaining 17¢ is usually free money.

## Patterns to Avoid
1. ❌ Both-sides buying (check event slug, not just condition ID)
2. ❌ Positions >$10 on anything except 90%+ WR wallets
3. ❌ Entry price below 40¢ (35% WR = money pit)
4. ❌ Midnight trading (29% WR)
5. ❌ US sports spreads and NHL games (coin flips)
6. ❌ International soccer friendlies (Liberia, Benin, etc.)
7. ❌ Large weather positions on exact temperatures (43% WR)
8. ❌ Trusting wallet WR inflated by short-duration coin-flip markets

## Priority Wallets
- **@tradecraft** `0xde9f...` — Tennis specialist, 2139% ROI
- **@coldmath** `0x594e...` — Weather via aviation data, $89K+
- Any wallet with >85% WR on >30 resolved in a SPECIFIC category

## Open Positions to Watch (32 active, $157 value)
- 13 likely winners (>90% price): $76 — let these ride
- 14 toss-ups (20-90%): $68 — monitor with trailing stops
- 3 likely losers (<20%): $11 — consider cutting for capital recovery

---
*This file is read by Claude Code at the start of every session.*
*Auto-updates after each trading day from Polymarket activity + positions API.*

## 2026-04-05 — Wave verification / infra notes

- **X intake:** Redis publish path is `integrations/x_intake/pipeline.py` (`publish_to_redis`, default out channel `notification-hub`). Added `integrations/x_intake/bridge.py` with `XIntakeBridge` so `from integrations.x_intake.bridge import XIntakeBridge` matches verification imports.
- **Kraken Avellaneda MM:** `polymarket-bot/src/main.py` uses `CryptoClient` with `dry_run` from env `KRAKEN_DRY_RUN` (default false). `AvellanedaMarketMaker.start()` awaits `await self._client.connect()`.
- **Auto-responder:** `draft_email` uses Zoho `mode: draft` only (no send). Redis notifications require `REDIS_URL`; publishes to `notifications:email` and pushes JSON to list `email:drafts` (no hardcoded Redis credentials in code).
