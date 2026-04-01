# Mount Clearance Validation Checklist
## Symphony Smart Homes — Standard Operating Procedure

---

## When to Run This Check
- Every time a client specifies TV mounts
- Every time a client specifies recessed TV boxes (Legrand or equivalent)
- Before any mount is added to a proposal or change order

---

## Step 1: Identify the Recessed Box

| Box Model | Recess Depth | Plug Protrusion from Wall |
|-----------|-------------|--------------------------|
| Legrand TV2MW (2-gang) | 3.5" into wall | 1–2" past wall face (with devices installed) |
| Legrand TV3WTVSSW (3-gang kit) | 2.25" into wall | 1.5–2.5" past wall face |
| Legrand TV1WMTVSSWCC2 (1-gang) | 3.5" into wall | 1–2" past wall face |
| Standard outlet (no recess) | 0" | 2–3" past wall face |

**Key fact:** Even with a recessed box, installed devices (duplex outlet, HDMI connectors, low-voltage jacks) still protrude forward of the wall surface. A recessed box does NOT mean flush connections.

**Typical plug protrusions:**
- Standard power plug: 1.5–2"
- HDMI connector (standard): 1.25–1.5"
- HDMI connector (right-angle): ~0.75"
- Coax/F-connector: ~1"
- Ethernet (RJ45): ~0.75"
- Brush plate (pass-through): 0" (flush)

---

## Step 2: Check Mount Wall Profile

| Mount Type | Typical Wall Profile | Clearance Rating |
|------------|---------------------|-----------------|
| Fixed/Flat (e.g., Mount-It MI-3447, Sanus MLL11) | 0.5–1.0" | FAIL — cannot clear recessed box plugs |
| Low-profile tilt (e.g., Strong Carbon SM-CB-T) | 2.6" | MARGINAL — clears plugs but tight service access |
| Advanced tilt (e.g., Sanus VLT7 Tilt 4D) | 2.1" collapsed, 6.8" extended | PASS — clears plugs, full service access |
| Full-motion articulating | 2.4–4.0" collapsed, 18–28" extended | PASS — full clearance and service access |
| Ceiling mount (e.g., Peerless-AV PLCM-2) | N/A — not wall-mounted | N/A |

---

## Step 3: Validation Rule

```
IF mount_wall_profile < max_plug_protrusion THEN
    FAIL — mount cannot clear recessed box connections
    ACTION: Recommend Sanus VLT7 Tilt 4D or equivalent tilt/articulating mount
    
IF mount_wall_profile >= max_plug_protrusion AND mount_wall_profile < (max_plug_protrusion + 1") THEN
    MARGINAL — mount clears plugs but service access is limited
    ACTION: Flag to client, recommend tilt mount for service access
    
IF mount_wall_profile >= (max_plug_protrusion + 1") THEN
    PASS — mount clears plugs with service margin
```

**Conservative rule:** Mount wall profile must be at least 2" to clear any recessed box with standard plugs. Anything under 2" requires right-angle adapters at minimum and is still marginal.

---

## Step 4: Additional Checks

### Tilt Requirement
- [ ] Is the TV mounted above eye level? (e.g., above fireplace, high on wall)
- [ ] If yes → tilt mount is required for viewing angle correction
- [ ] Fixed mounts offer 0° tilt — permanent glare and suboptimal angle

### Service Access
- [ ] Can an HDMI cable be swapped without removing the TV?
- [ ] Can a power connection be reset without removing the TV?
- [ ] If no to either → recommend tilt or articulating mount with extension

### Weight Capacity
- [ ] Mount weight capacity >= TV weight + 20% safety margin
- [ ] Check VESA pattern compatibility (mount vs TV back panel)

### TV Size vs Mount Rating
- [ ] TV screen size within mount's rated range
- [ ] For 100"+ TVs: verify mount explicitly supports this size (most top out at 90")

---

## Default Recommendation

**Sanus VLT7 Advanced Tilt 4D** for all wall-mount locations in C4 integrated homes:
- 2.1" collapsed — clears recessed box plugs
- 6.8" extension — full service access
- +7°/-12° tilt — glare correction for above-eye mounts
- 15° L/R swivel — angle toward seating
- 150 lb capacity — covers up to 100" panels
- VESA 200×100 through 600×400
- 42"–90" TV range
- 10-year warranty
- Available through Snap One dealer channel

**Exception:** Ceiling-mounted TVs (e.g., Hearth Room with Peerless-AV PLCM-2) — no change needed.

**Exception:** TVs 100"+ may need the Sanus BLF528 full-motion or equivalent rated for the size/weight.

---

## Red Flags — Auto-Flag These to Matt

1. Client specs fixed mount + recessed box → always flag
2. Client specs mount with < 2" wall profile → always flag
3. Client specs TV > 90" with mount rated to 90" → always flag
4. Client specs mount with no tilt + TV above eye level → always flag
5. Mount-It or other consumer-grade mounts in a $30K+ project → always flag
