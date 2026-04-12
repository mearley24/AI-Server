# TV & Mount Recommendations Workflow

## When to Use
When a client provides a TV schedule, asks about TV options, or specifies mounts/recessed boxes. Run this for any project where TVs are in scope.

## Steps

### Phase 1: Validate Client Selections
1. **C4 Driver Check** — For every TV model: look up in `c4_tv_driver_reference.json`. Classify as: Native SDDP / 3rd-Party IP / IR Only / No Driver. Flag any NOT Native SDDP.
2. **Mount Clearance Check** — For every mount + recessed box: run `mount-clearance-validation`. Check wall profile vs plug protrusion. Flag any that FAIL.
3. **Price Volatility Check** — For any consumer-brand TV (TCL, Hisense, Vizio): check 3 retailers (Best Buy, Walmart, Amazon). Flag if price swing > $200/unit.
4. **EOL Check** — Flag any model 2+ years old or showing "limited stock" / "clearance" pricing.

### Phase 2: Build Alternatives (if needed)
5. Source Samsung alternatives at comparable size from Mountain West (mwd1.com) for dealer pricing.
6. **Model hierarchy (prefer in order):** QN80F/QN90F → S85F/S90F → Q8F → Q7F/Q6F.
7. Build three-tier packages: **Essential** (QLED throughout), **Recommended** (OLED main/QLED bedrooms), **Premium** (OLED everywhere). Each shows: location / model / type / price / total.

### Phase 3: Build the Document
8. Generate PDF using `build_tv_pdf_v2.py` (or current template). Required sections:
   - Introduction + "we will support whatever you choose" language
   - Price volatility note (if consumer-brand TVs)
   - C4 integration explanation + specific integration warning for client's TVs
   - Three package options with pricing tables
   - Comparison summary table
   - Payment terms: full payment required to lock pricing
   - Mount recommendations with clearance analysis
9. **Pre-delivery checklist:**
   - [ ] All prices match Samsung.com current pricing
   - [ ] Payment terms included
   - [ ] Install says "standard service rates" (NOT "included")
   - [ ] C4 warning specific to client's exact models
   - [ ] Mount clearance uses client's actual recessed box model
   - [ ] Version number in filename: `[Address]_TV_Mount_Recommendations_V[#].pdf`

### Phase 4: Deliver
10. Save to `Projects/[Project]/Client/` in Dropbox. Verify file exists.
11. Generate individual share link (not folder link).
12. Draft email in Zoho (hold for Matt review — do NOT send).
13. Create/update Linear issue, link to Dropbox file.

## Notes
- TV margin is minimal — revenue is in labor and programming. Sell at Samsung.com current price.
- Never promise "included" installation — always "standard service rates".
- Standard non-native warning: *"Based on our experience, third-party drivers and IR control create support issues that are difficult to resolve."*
- **Red flags → escalate to Matt:** Client insists on non-native after seeing recs; asks for below-retail pricing; wants Symphony to warranty non-Symphony TVs; 100"+ TV with no mount selected; TV model not in C4 driver reference.

## Related
- `mount-clearance-validation.md`
- `knowledge/hardware/c4_tv_driver_reference.md`
