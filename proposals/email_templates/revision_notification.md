# Proposal Revision Notification Email Template

**Purpose:** Notify client when a proposal has been updated/revised  
**From:** [TEAM_EMAIL]  
**To:** [CLIENT_EMAIL]  
**Subject:** [PROJECT_NAME] — Updated Proposal (v[VERSION])  
**Trigger:** When proposal_engine.revise() is called and new version is generated

---

## Subject Line Variants

**Standard revision:**  
`[PROJECT_NAME] — Updated Proposal (v[VERSION])`

**Scope-specific:**  
`[PROJECT_NAME] — Updated: [CHANGE_SUMMARY] (v[VERSION])`

---

## Email Body (Scope Adjustment)

---

Hi [CLIENT_FIRST_NAME],

Attached is the updated proposal for **[PROJECT_NAME]** — version [VERSION].

**What changed from v[PREVIOUS_VERSION]:**

[CHANGE_1 — e.g., "Added the outdoor patio audio zone you mentioned — 2 Triad outdoor speakers and a zone added to the Triad amplifier"]

[CHANGE_2 — e.g., "Swapped the theater projector to the Epson LS12000 per your request — updated pricing reflects this"]

[CHANGE_3 — e.g., "Removed the Garage audio zone to bring the project within your target budget"]

**Updated Pricing:**

| | Previous (v[PREV_VERSION]) | Updated (v[VERSION]) | Change |
|---|---|---|---|
| Equipment | [PREV_EQ_PRICE] | [NEW_EQ_PRICE] | [DELTA] |
| Labor | [PREV_LABOR] | [NEW_LABOR] | [DELTA] |
| **Total** | **[PREV_TOTAL]** | **[NEW_TOTAL]** | **[DELTA]** |

*All other terms, payment schedule, and timeline remain unchanged.*

Let me know if this looks right, or if there are any other adjustments you'd like to explore.

[SENDER_NAME]  
Symphony Smart Homes  
[PHONE] | [EMAIL]

---

## Email Body (Minor Correction / Clarification)

---

Hi [CLIENT_FIRST_NAME],

I've sent over an updated proposal (v[VERSION]) for [PROJECT_NAME].

This is a minor correction — [DESCRIPTION: e.g., "I noticed the speaker quantity for the Master Bedroom was listed as 4 in error — it should be 2. This has been corrected; the pricing impact is [none / $X]."].

Everything else remains the same. No action required unless you have questions.

[SENDER_NAME]  
Symphony Smart Homes  
[PHONE] | [EMAIL]

---

## Email Body (Price Update — Pre-Expiry)

---

Hi [CLIENT_FIRST_NAME],

The pricing on the [PROJECT_NAME] proposal was updated today to reflect a recent 
change from our distributor.

**Summary:**
- [ITEM]: [PREV_PRICE] → [NEW_PRICE] ([REASON: e.g., "Araknis updated MSRP"])
- Project total adjustment: [DELTA] ([increase / decrease])

The revised proposal (v[VERSION]) is attached. All scope remains identical.

I wanted to be transparent about this change before you signed. If you have any 
concerns or questions, please reach out.

[SENDER_NAME]  
Symphony Smart Homes  
[PHONE] | [EMAIL]

---

## Usage Notes

- **Always include version numbers** in subject and body — clients compare docs
- **Change summary must be specific** — never send "minor updates were made" with no detail
- **Price table:** Only include if pricing changed — omit for scope-only or typo corrections
- **Auto-trigger:** Bob fires this template whenever proposal_engine.revise() produces a new version
- **D-Tools:** Ensure D-Tools project is updated to match the new version before sending
