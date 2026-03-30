# Symphony Smart Homes — Linear Workflow Draft

**For Review by Matthew Earley — March 30, 2026**
Nothing below has been pushed. All changes pending your approval.

---

## Part 1: Topletz Issue Updates

### SYM-23 — Review Addendum #1 and finalize scope changes
- **Current status:** Todo
- **Proposed status:** ✅ Done
- **Reason:** Addendum #1 fully documented in deliverables package. Control4 native lighting replaces Lutron RA3 (confirmed). ClareOne security removed (confirmed). Amplifiers confirmed NEW with warranties. All scope changes captured in Change Log with approval references.

### SYM-24 — Configure network VLANs per client requirements
- **Current status:** Todo
- **Proposed status:** 🟡 In Progress
- **Updated description:** "VLAN topology designed and documented in deliverables package (5 VLANs: Management, Control, AV, Guest, Security). IP addressing pre-assigned. Inter-VLAN firewall rules defined. Commissioning on hardware pending installation."
- **Reason:** Design work is done. Can't configure on hardware until gear is racked.

### SYM-25 — Order equipment from Snap One / D-Tools
- **Current status:** Todo
- **Proposed status:** Todo (no change)
- **Updated description:** Fix old total — change "$56,858.57" → "$58,991.08 (Q-196 V2)"
- **Reason:** Blocked until deposit received. Description had stale pricing from V1.

### SYM-26 — Finalize agreement and contract
- **Current status:** Todo
- **Proposed status:** 🟡 In Progress
- **Updated description:** "Deliverables package and Q-196 V2 proposal ($58,991.08) sent to Steve 3/30. Awaiting client review and sign-off. Need formal agreement/contract drafted and signed before deposit. Reference Steve's 'Clarity of Future Responsibility' email for terms."
- **Reason:** Deliverables sent today. This is now the active blocker.

### SYM-27 — Schedule installation dates
- **Current status:** Todo
- **Proposed status:** Todo (no change)
- **Reason:** Blocked until contract signed + deposit received.

### SYM-28 — Control4 lighting system programming
- **Current status:** Todo
- **Proposed status:** Todo (no change)
- **Reason:** Blocked until lighting walkthrough with Steve (may reduce 41 devices via keypad consolidation).

### SYM-29 — Commission system and client walkthrough
- **Current status:** Todo
- **Proposed status:** Todo (no change)
- **Reason:** Last phase. No changes needed yet.

### NEW ISSUE — Send deliverables package + proposal to client
- **Proposed status:** ✅ Done
- **Priority:** Urgent
- **Description:** "Deliverables package (11-page PDF: rack elevation, network topology, lighting schedule, scope summary with change log) and D-Tools Q-196 V2 proposal ($58,991.08) sent to Steve Topletz on 3/30/2026. All warranty and spec claims verified against manufacturer data."
- **Reason:** This step happened today. Documenting it in the project timeline.

### NEW ISSUE — Client reviews deliverables and provides feedback
- **Proposed status:** 🟡 In Progress
- **Priority:** Urgent
- **Description:** "Waiting on Steve Topletz to review deliverables package and Q-196 V2. Pending decisions: (1) iPad vs C4-T5IW8 touchscreens (Deviation #4), (2) Lighting walkthrough scheduling, (3) Payment schedule acceptance. Track all client feedback here."
- **Reason:** This is the current blocker. Captures all pending client decisions in one place.

---

## Part 2: Standardized Symphony Project Template

Every new Symphony Smart Homes project gets these phases/issues automatically. This is the reusable template Bob follows for any new job.

### Phase 1: Pre-Sale & Scope (before any money changes hands)

| # | Issue Title | Priority | Description |
|---|------------|----------|-------------|
| 1 | Initial client consultation & RFP review | High | Review client RFP/requirements. Document all preferences, concerns, and special requests. Note client communication style and decision-making pace. |
| 2 | Design system architecture & create proposal | High | D-Tools proposal creation. Rack elevation, network topology, audio zones, lighting layout. All equipment specified with model numbers. |
| 3 | Build deliverables package | High | Compile rack elevation drawing, network topology, lighting load schedule, scope summary with change log. Verify ALL claims (warranties, specs, power) against manufacturer data before sending. |
| 4 | **Review deliverables internally** | Urgent | Matthew reviews all documents before anything goes to client. No exceptions. Check: correct client name, correct pricing, correct equipment, no placeholder data, all claims verified. |
| 5 | Send deliverables + proposal to client | High | Send verified deliverables package and D-Tools proposal to client. Log date sent. |
| 6 | Client review & pending decisions | Urgent | Track all client feedback, questions, and pending decisions. Do not proceed until all open items resolved. |
| 7 | Finalize agreement & contract | Urgent | Formal agreement/contract signed. Reference any client-specific terms (e.g., responsibility clauses). ALL paperwork finalized before first check or first wire pulled. |

### Phase 2: Pre-Wire & Procurement (after deposit received)

| # | Issue Title | Priority | Description |
|---|------------|----------|-------------|
| 8 | Collect deposit | Urgent | Deposit received per payment schedule. Log amount, date, method. No equipment ordered until deposit clears. |
| 9 | Order equipment from Snap One / D-Tools | High | Pull equipment list from D-Tools opportunity. Submit purchase orders. Track lead times. No substitutions without written client approval. |
| 10 | On-site walkthrough with client | High | Walk every room with client. Confirm device placement, keypad locations, speaker positions, AP mounting points. May reduce device count through consolidation. Document all decisions. |
| 11 | Pre-wire rough-in | Medium | Run all low-voltage cabling. Speaker wire, Cat6, control wiring. Photo-document all runs before drywall. |
| 12 | Pre-wire inspection & sign-off | Medium | Verify all runs, label everything, photo-document. Collect pre-wire completion payment per schedule. |

### Phase 3: Trim & Installation (after pre-wire complete)

| # | Issue Title | Priority | Description |
|---|------------|----------|-------------|
| 13 | Rack build & equipment mounting | High | Mount rack, install all equipment per rack elevation drawing. Cable management, power connections, ventilation clearances per manufacturer specs. |
| 14 | Network commissioning | High | Configure VLANs, firewall rules, DHCP reservations, WiFi SSIDs. Assign IPs per network topology document. Populate MAC/serial fields. |
| 15 | Audio system commissioning | Medium | Wire amps to speakers, configure zones in AMS, test every zone. Level matching and EQ. |
| 16 | Lighting programming | Medium | Program all scenes, keypads, schedules. Test every load. Confirm no ghosting (Steve's #1 concern). |
| 17 | Control4 programming & integration | High | Full system programming: lighting scenes, audio zones, shade integration, scheduling, touchscreen/remote UI. |
| 18 | Trim completion payment | Medium | Collect trim completion payment per schedule. |

### Phase 4: Commissioning & Handoff

| # | Issue Title | Priority | Description |
|---|------------|----------|-------------|
| 19 | Full system QA & punch list | High | Test every subsystem end-to-end. Create punch list. Fix all issues before client walkthrough. |
| 20 | Client walkthrough & training | High | Walk client through entire system. Demonstrate all scenes, zones, remotes, touchscreens. Address every question. Client is detail-oriented — be thorough. |
| 21 | Final sign-off & completion payment | Urgent | Client signs off on completed system. Collect final payment per schedule. |
| 22 | Warranty documentation & handoff | Medium | Provide all warranty info, manuals, login credentials, network diagram. Store in client's project folder on iCloud. |

### Workflow Rules (apply to every project)

1. **All outbound emails drafted in Zoho, never auto-sent.** Bob drafts the email in Zoho Mail drafts folder, then notifies Matthew via iMessage that a draft is ready for review. Matthew reviews, requests changes, or sends it himself. No email ever leaves the system without Matthew hitting send.
2. **ALL paperwork finalized before first check or first wire pulled.** No spending money until agreement is signed.
3. **No substitutions without written client approval.** Everything matches the D-Tools quote exactly.
4. **Verify all claims against manufacturer data.** Warranty years, power specs, clearances — nothing fabricated.
5. **When a step needs client input, the next issue is always "Send to client + wait for response."** Don't skip the handoff.
6. **Document every client decision with approval reference** (email subject, date, who approved).
7. **Photo-document all pre-wire runs** before drywall closes.
8. **Populate commissioning fields on-site** (MAC, serial, switch port) — not before.
9. **Client preferences tracked from day one** — communication style, concerns, decision pace.

---

## How This Gets Used

**For Topletz (now):** Push the issue updates in Part 1.

**For every new project:** When a new job is won (enters WON phase in job lifecycle), Bob auto-creates a Linear project with all 22 issues from the template, pre-filled with client name, address, and D-Tools proposal reference. Issues start in Backlog and move forward as work progresses.

**In the AI-Server repo:** This template gets codified in `job_lifecycle.py` so when a job transitions to WON, the Linear project + issues are created automatically.

---

**Awaiting your review. Nothing has been pushed to Linear yet.**
