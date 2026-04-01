# TV & Mount Recommendations — Operations Playbook
## Symphony Smart Homes — Bob & Team Reference

---

## Purpose
When a client provides a TV schedule or asks about TVs for their integrated home, this playbook defines the standard workflow for evaluating, recommending, and delivering a TV & Mount Recommendations document.

---

## Trigger
- Client sends a TV schedule, TV wish list, or asks about TV options
- Client specifies mounts or recessed TV boxes in their plans
- New project intake where TVs are in scope

---

## Workflow

### Phase 1: Validate Client Selections (Automated)

**Step 1.1 — C4 Driver Check**
For every TV model the client specified:
1. Look up in `/c4_tv_driver_reference.json`
2. Classify each as: Native SDDP / 3rd-Party IP / IR Only / No Driver
3. Flag any TV that is NOT Native SDDP

**Decision tree:**
- All Native SDDP → proceed to mount validation only
- Any 3rd-party/IR/None → build full TV recommendations document

**Step 1.2 — Mount Clearance Check**
For every mount + recessed box combination:
1. Follow `/ssh_mount_clearance_validation.md`
2. Check wall profile vs plug protrusion
3. Flag any mount that fails clearance

**Step 1.3 — Price Volatility Check**
For any consumer-brand TV (TCL, Hisense, Vizio):
1. Check current pricing on 3 retailers (Best Buy, Walmart, Amazon)
2. Note the price range observed
3. Flag if swing > $200 per unit

**Step 1.4 — Discontinued/End-of-Life Check**
- Is the model current year or prior year?
- Is it still in production and readily available?
- Flag any model 2+ years old or showing "limited stock" / "clearance" pricing

---

### Phase 2: Build Alternatives (If Needed)

**Step 2.1 — Source Dealer Alternatives**
For each flagged TV, find a Samsung alternative at a comparable size:
- Check Mountain West (mwd1.com) for dealer pricing
- Match Samsung.com current retail as sell price
- Prioritize: Native SDDP > same or similar size > comparable price tier

**Model hierarchy (prefer in this order):**
1. Samsung QN80F / QN90F (Neo QLED Mini LED) — for hero/large locations
2. Samsung S85F / S90F (QD-OLED) — for main living areas
3. Samsung Q8F (QLED) — for bedrooms / secondary locations
4. Samsung Q7F / Q6F (QLED) — budget tier if needed

**Step 2.2 — Build Three-Tier Packages**
Every recommendation document offers three options:
- **Essential** — QLED throughout, best value, all native C4
- **Recommended** — OLED in main rooms, QLED in bedrooms
- **Premium** — OLED everywhere

Each package shows:
- Location / Model / Type / Price per unit
- Total TV cost
- Comparison table (C4 integration, IR flashers, drivers, warranty, firmware)

**Step 2.3 — Pricing Rules**
- Sell price = Samsung.com current price (match exactly)
- Note if prices are sale prices (subject to change)
- Include payment terms: "Full payment for TV equipment required at time of package selection to lock pricing. Symphony will purchase, receive, and store all units until installation date."
- Include price volatility table for client's original selections if applicable

---

### Phase 3: Build the Document

**Step 3.1 — Generate PDF**
Use the TV recommendations PDF template (`build_tv_pdf_v2.py` or future templated version)

**Required sections:**
1. Introduction — "not meant to replace your selections, we support whatever you choose"
2. Price volatility note (if client has consumer-brand TVs)
3. C4 Integration explanation (Native SDDP / 3rd-party / IR / None)
4. Integration warning callout — flag exactly which of their TVs have issues
5. Three package options with pricing tables
6. Comparison summary table
7. Fine print with payment terms and service rate language
8. Consumer brand risk section (warranty, failure rates, firmware)
9. Mount recommendations with clearance analysis
10. Summary with three-tier overview
11. Next steps
12. Sources with clickable URLs

**Filename format:** `[ProjectAddress]_TV_Mount_Recommendations_V[#].pdf`
Example: `84_Aspen_Meadow_TV_Mount_Recommendations_V3.pdf`

**Step 3.2 — Review Checklist Before Delivery**
- [ ] All prices match Samsung.com current pricing
- [ ] Payment terms included (full payment to lock pricing)
- [ ] Install/programming says "standard service rates" (NOT "included")
- [ ] C4 integration warning is specific to client's exact models
- [ ] Mount clearance analysis uses client's actual recessed box model
- [ ] Version number in filename
- [ ] "We will support whatever you choose" language present
- [ ] Sources with clickable URLs on final page
- [ ] No text overflow or layout issues in PDF

---

### Phase 4: Deliver

**Step 4.1 — Dropbox**
1. Save PDF to `Projects/[Project]/Client/`
2. VERIFY file exists in the folder (do not assume)
3. Generate individual share link for the PDF (not a folder link)

**Step 4.2 — Email Draft**
1. Draft email in Zoho (mode: draft)
2. Include: confirmation of any pending alignment items + link to PDF
3. Frame as informational: "worth a read before we lock this in"
4. Hold for Matt's review — do NOT send

**Step 4.3 — Linear**
1. Create or update issue for TV/mount recommendations
2. Link to Dropbox file
3. Note which package client selects (when decided)

---

## Key Principles

### Tone
- Never hard-sell. Frame as "here's what we recommend and why"
- Always include "we will support whatever you choose"
- Be transparent about limitations of non-native TVs — don't hide it
- Use "based on our experience" when warning about third-party drivers

### Business Model
- TV margin is minimal — revenue is in labor and programming
- Sell price matches Samsung.com (client can verify)
- The value proposition is: one vendor, one call, native integration, locked pricing, dealer warranty
- Never promise "included" installation — always "standard service rates"

### Consumer Brand Warning Language
Standard language for any non-native TV:
> "Based on our experience, third-party drivers and IR control create support issues that are difficult to resolve and compromise the integrated experience this system is designed to deliver. We strongly recommend native integration for every TV in the home."

> "If you'd like to keep your current selections, we will install them — but want to be transparent that Control4 controllability may be limited or inconsistent on non-native models."

### Red Flags — Always Escalate to Matt
1. Client insists on non-native TVs after seeing recommendations
2. Client asks for pricing below Samsung.com retail
3. Client wants Symphony to warranty non-Symphony-supplied TVs
4. Client specifies 100"+ TV with no mount selected
5. Any TV model not in the C4 driver reference (unknown compatibility)

---

## Reference Files

| File | Location | Purpose |
|------|----------|---------|
| C4 Driver Reference (JSON) | `/c4_tv_driver_reference.json` | Machine-readable driver lookup |
| C4 Driver Reference (MD) | `/c4_tv_driver_reference.md` | Human-readable driver reference |
| Mount Clearance Validation | `/ssh_mount_clearance_validation.md` | Mount validation checklist |
| PDF Generator Template | `/build_tv_pdf_v2.py` | Python script to generate recommendation PDFs |
| This Playbook | `/ssh_tv_mount_recommendations_playbook.md` | Full workflow reference |

---

## Version History
- V1 — April 1, 2026 — Initial playbook created from Topletz 84 Aspen Meadow project
