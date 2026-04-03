# Execution Order — Dependency-Aware Waves

Derived from the tier structure in README.md. Items within each wave can run in parallel (no hard dependencies between them). Waves must complete before the next wave begins.

**Key dependency rules applied:**
- Auto-21 (position reconciliation) → must precede Auto-6, Auto-7, Auto-11 (new strategies)
- Auto-5 (docker health) → foundational; run first
- Auto-8 (risk management) → must precede any new strategies
- Auto-29 (verify implementations) → runs after all DONE items and earlier waves are stable
- API-11 (Bob's Brain) → glue layer; runs after individual services are solid
- API-13 (client lifecycle) → depends on Auto-16 (proposal engine) + Auto-18 (Dropbox sync)
- Auto-23 (cost optimization) → benefits from API-11 being complete first

---

## Wave 0 — Foundational Infrastructure
*Nothing else can run reliably without this.*

- [ ] **Auto-5** · docker-health-startup — health checks + startup orchestration

---

## Wave 1 — Safety & Reconciliation
*Risk controls and position truth must exist before any trading logic runs.*

Run in parallel:
- [ ] **Auto-8** · risk-management-hardening — volume filter, whale gate, bankroll sync, redemption audit
- [ ] **Auto-21** · position-reconciliation — on-chain position sync, true portfolio value, startup recovery *(required before Auto-6, 7, 11)*

---

## Wave 2 — Core Trading Substrate
*Foundation APIs and intelligence feeds that strategies depend on.*

Run in parallel:
- [ ] **API-1** · self-improving-trading-bot — RBI pipeline, CVD, multi-strategy wiring *(depends on Wave 1)*
- [ ] **API-2** · bob-business-operator — Bob handles business autonomously
- [ ] **Auto-10** · intel-feeds-deploy — deploy the trading cortex
- [ ] **Auto-13** · test-suite — comprehensive test coverage *(run early; catches regressions in later waves)*
- [ ] **Auto-19** · security-hardening — secrets, auth, audit trail

---

## Wave 3 — New Trading Strategies
*Auto-21 and Auto-8 from Wave 1 are hard prerequisites for all items here.*

Run in parallel:
- [ ] **Auto-6** · mean-reversion-strategy — fade overnight manipulation *(requires Auto-21, Auto-8)*
- [ ] **Auto-7** · presolution-scalp — tail risk scalping near resolution *(requires Auto-21, Auto-8)*
- [ ] **Auto-11** · stink-bid-flash-crash — stink bids + flash crash + sports arb wire-up *(requires Auto-21, Auto-8)*
- [ ] **Auto-2** · liquidity-provision — market making *(requires Auto-8)*
- [ ] **Auto-1** · cross-platform-arb — Kalshi vs Polymarket bracket arb *(requires Auto-21)*

---

## Wave 4 — Performance Measurement & Analytics
*Strategies must exist before measuring them.*

Run in parallel:
- [ ] **Auto-20** · performance-analytics — trade database, backtester, self-tuning *(requires Wave 3)*
- [ ] **Auto-14** · network-guard-deploy — network monitoring daemon
- [ ] **Auto-15** · ollama-maestro-setup — local LLM on 64GB iMac

---

## Wave 5 — Business Automation Substrate
*Proposal engine and file sync must be ready before client lifecycle (API-13) can run.*

Run in parallel:
- [ ] **API-5** · mission-control-dashboard — real-time service dashboard
- [ ] **API-6** · hermes-multi-platform — unified messaging (iMessage + email + Telegram)
- [ ] **Auto-9** · knowledge-layer-assembler — SOW assembler + preflight checker
- [ ] **Auto-16** · proposal-engine-automation — end-to-end proposal pipeline *(required by API-13)*
- [ ] **Auto-18** · dropbox-icloud-sync — file pipeline fix *(required by API-13)*
- [ ] **Auto-17** · daily-briefing-upgrade — unified morning report
- [ ] **Auto-3** · client-portal-voice — client portal voice interface

---

## Wave 6 — The Brain (Glue Layer)
*Individual services from Waves 2–5 must be solid before wiring them together.*

- [ ] **API-11** · bobs-brain-unified-context — event bus, context store, decision engine *(depends on Waves 2–5)*

Then in parallel once API-11 is complete:
- [ ] **API-12** · profit-reinvestment-loop — treasury, auto-scaling bankroll, financial dashboard *(depends on API-11)*
- [ ] **API-13** · symphony-client-lifecycle — zero-touch project management, lead to handoff *(depends on Auto-16, Auto-18)*

---

## Wave 7 — Cost Optimization & Context Efficiency
*API-11 must be complete; optimizing a system that isn't wired yet wastes effort.*

Run in parallel:
- [ ] **Auto-23** · cost-optimization — LLM router, caching, local fallbacks, $50/month target *(depends on API-11)*
- [ ] **Auto-28** · context-preprocessor — credit-saving middleware, session manager, clipboard compressor
- [ ] **Auto-25** · apple-notes-indexer — index, categorize, flag for cleanup, extract codes + photos
- [ ] **API-3** · neural-map — knowledge graph visualization
- [ ] **API-4** · ensemble-weather-models — ECMWF + GFS ensemble for tighter brackets
- [ ] **Auto-22** · multi-agent-learning — employee chit-chat, cortex curator, overnight learning

---

## Wave 8 — Verification Pass
*Run after the system is substantially complete. Fixes broken imports and validates integrations.*

- [ ] **Auto-29** · verify-all-implementations — verify API-1/2/3 + all DONEs, fix broken imports, integration test *(run last among core infrastructure)*

---

## Wave 9 — Revenue & Product Layer
*Stable, verified core required before external-facing products.*

Run in parallel:
- [ ] **API-8** · voice-receptionist-v2 — Twilio + OpenAI Realtime phone answering
- [ ] **API-9** · client-ai-concierge-deploy — first customer AI appliance
- [ ] **API-10** · trading-mobile-app — iOS trading app API
- [ ] **Auto-12** · clawwork-activation — Bob's freelance side hustle
- [ ] **Auto-4** · bookmark-processor — X bookmark processing
- [ ] **Auto-27** · x-twitter-autoposter — Bob posts to @symphonysmart with approval queue

---

## Wave 10 — Dreamland (Endgame)
*Long-horizon, non-blocking. Run whenever capacity allows.*

Run in parallel:
- [ ] **API-14** · system-design-graph — compatibility intelligence, design validation, wiring diagrams
- [ ] **API-15** · symphony-ops-web-dashboard — business ops GUI (product catalog, SOW builder, project tracker)
- [ ] **Auto-24** · portfolio-website — auto-generated portfolio from project photos

---

## Summary Dependency Graph

```
Wave 0: Auto-5
          │
Wave 1: Auto-8, Auto-21
          │
Wave 2: API-1, API-2, Auto-10, Auto-13, Auto-19
          │
Wave 3: Auto-6, Auto-7, Auto-11, Auto-2, Auto-1   (blocked on Auto-21 + Auto-8)
          │
Wave 4: Auto-20, Auto-14, Auto-15
          │
Wave 5: API-5, API-6, Auto-9, Auto-16, Auto-18, Auto-17, Auto-3
          │
Wave 6: API-11  ──► API-12, API-13  (API-13 also blocked on Auto-16 + Auto-18)
          │
Wave 7: Auto-23, Auto-28, Auto-25, API-3, API-4, Auto-22
          │
Wave 8: Auto-29  (verification sweep)
          │
Wave 9: API-8, API-9, API-10, Auto-12, Auto-4, Auto-27
          │
Wave 10: API-14, API-15, Auto-24
```

---

*Last updated: 2026-04-03*
