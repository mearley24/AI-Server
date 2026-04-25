# Client Triage Bucket Scoring Improvement — Verification Report

**Date**: 2026-04-25T16:45Z
**Result**: PASS — 749 tests green

## Before / After

| Bucket | Before | After |
|---|---|---|
| high_value | 3 | 31 |
| ambiguous | 168 | 141 |
| low_priority | 96 | 95 |
| hidden_personal | 0 | 0 |

## Root causes fixed

### Bug: tech_s==2 fell to conf=0.25
In analyze_thread_assist, there was no branch for tech_s==2 standalone (only tech_s>=3 and tech_s==1). A thread with exactly 2 tech signals would fall to the else branch (conf=0.25). Fixed by adding explicit elif tech_s==2 → conf=0.60 branch.

### Bug: _determine_triage_bucket default was ambiguous
Any work thread that didn't match a specific rule fell to ambiguous. Changed default to low_priority. Ambiguous now requires genuine conflicting signals.

### Bug: named contacts with any tech signals not reaching high_value
Named contacts needed assist_conf >= 0.65 or work_confidence >= 0.80 to reach high_value. Most named contacts with 1-2 tech signals had conf=0.25-0.35 due to the tech_s==2 bug and the sparse signal scoring. Fixed: named + any tech signal → high_value.

### Bug: GC contacts bypassed signal check entirely
All GC contacts went to ambiguous immediately, regardless of signal strength. Fixed: GC + tech_s >= 3 → high_value; GC + tech_s >= 1 and no restaurant → ambiguous-tech; GC + restaurant → ambiguous-restaurant.

### Bug: restaurant-heavy contacts reaching high_value via rule 4
Unnamed contacts with conf >= 0.70 from restaurant signals (not tech) were landing in high_value with reason 'strong smart-home signals'. Fixed rule 4 to require tech_s >= 1.

## Changes made

### review_client_threads.py
- _TECH_TERMS expanded: low voltage, low-voltage, rough in, rough-in, trim out, motorized, speaker, subwoofer, amplifier, structured wiring, cat6, ethernet, hdmi, audio video, av system
- analyze_thread_assist: added elif tech_s==2 → conf=0.60; added single restaurant_s=1 and builder_s=1 branches; GC branches now distinguish tech_s>=3 vs tech_s>=1 vs no signals; raised tech_s==1 conf from 0.35 to 0.45

### auto_triage_client_threads.py
- _determine_triage_bucket completely rewritten:
  - GC rule: tech>=3 → high_value; tech>=1+no restaurant → ambiguous-tech; restaurant → ambiguous-restaurant
  - Named: any tech signal → high_value; conf>=0.50 → high_value; wconf>=0.75+msgs>=5 → high_value; msgs>=15+wconf>=0.50 → high_value; weak wconf → ambiguous
  - Unnamed: tech>=3 or (conf>=0.70 and tech>=1) → high_value; tech>=2+msgs>=10+restaurant<2 → high_value; large work thread (100+) + tech → high_value
  - Builder domain → ambiguous; restaurant domain → ambiguous; mixed with substance → ambiguous; old threads → ambiguous; large active work → ambiguous
  - Default changed from ambiguous to low_priority
- _print_bucket_summary shows tech/rest/build scores + evidence per entry

## Top 5 high_value examples

1. +19***09 — unnamed, tech=5, lutron/install/project — 17 msgs
2. +13***95 — unnamed, tech=5, lighting/lutron/hdmi — 15 msgs
3. +13***57 — unnamed, tech=4, rack/projector/screen — 24 msgs
4. Tori Sold Audi — named, wconf=0.75, 39 msgs
5. Carter — named, wconf=0.75, 61 msgs

## Tests: 749 passed (31 new scoring-specific tests in test_auto_triage_client_threads.py)
