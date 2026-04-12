# Mount Clearance Validation

## When to Use
Every time a client specifies TV mounts or recessed TV boxes (Legrand or equivalent). Before any mount is added to a proposal or change order.

## Steps

1. **Identify the recessed box** — note its plug protrusion from wall face:
   - Legrand TV2MW (2-gang): 1–2" protrusion
   - Legrand TV3WTVSSW (3-gang): 1.5–2.5" protrusion
   - Legrand TV1WMTVSSWCC2 (1-gang): 1–2" protrusion
   - Standard outlet (no recess): 2–3" protrusion
   - *Even with a recessed box, devices still protrude beyond the wall face.*

2. **Check mount wall profile:**
   - Fixed/Flat (Mount-It, Sanus MLL11): 0.5–1.0" → **FAIL**
   - Low-profile tilt (Strong Carbon SM-CB-T): 2.6" → **MARGINAL**
   - Advanced tilt (Sanus VLT7): 2.1"–6.8" → **PASS**
   - Full-motion articulating: 2.4"–4.0" → **PASS**

3. **Apply rule:**
   - `wall_profile < max_protrusion` → FAIL → recommend Sanus VLT7 or equivalent
   - `wall_profile ≥ protrusion but < protrusion + 1"` → MARGINAL → flag to client
   - `wall_profile ≥ protrusion + 1"` → PASS

4. **Additional checks:**
   - [ ] TV above eye level? If yes → tilt mount required
   - [ ] Can HDMI be swapped without removing TV? If no → tilt or articulating mount
   - [ ] Mount weight capacity ≥ TV weight + 20%
   - [ ] VESA pattern compatible
   - [ ] For 100"+ TVs: verify mount explicitly supports this size

## Notes
- **Default recommendation:** Sanus VLT7 Advanced Tilt 4D for all C4 integrated wall-mount locations. 2.1" collapsed, 6.8" extended, ±7°/12° tilt, 150 lb capacity, 42"–90", 10-year warranty.
- **Exception:** Ceiling mounts (Peerless-AV PLCM-2) — no clearance issue.
- **Exception:** TVs 100"+ → Sanus BLF528 or equivalent rated for size/weight.
- Conservative rule: mount wall profile must be ≥ 2" for any recessed box with standard plugs.

## Red Flags — Auto-Flag to Matt
1. Fixed mount + recessed box (always fails)
2. Mount with < 2" wall profile
3. TV > 90" with mount rated to 90"
4. Fixed mount + TV above eye level
5. Consumer-grade mount (Mount-It, etc.) in a $30K+ project

## Related
- `tv-mount-recommendations.md`
- `knowledge/hardware/c4_tv_driver_reference.md`
