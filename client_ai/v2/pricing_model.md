# Symphony Concierge — Pricing Model & Business Case

*Internal document | Symphony Smart Homes | v2.0*

---

## Executive Summary

Symphony Concierge is a recurring-revenue product that leverages existing installation
relationships. Each unit generates **$49–$199/month** in high-margin subscription
revenue after a one-time hardware and setup fee. The product differentiates Symphony
from every other local integrator — no Control4 dealer, no Savant dealer, and no
Crestron programmer offers a private, local AI assistant.

**Key numbers:**
- Hardware + install: $999–$3,000 per client (one-time)
- Monthly recurring: $49–$199 per client
- Fleet of 30 clients: ~$25,000–$60,000 ARR
- Support cost reduction: ~$182/client/year
- Target payback period: 6–10 months

---

## Hardware Cost Analysis

### Tier 1 — Budget (Raspberry Pi 5)

| Item | Cost |
|---|---|
| Hardware BOM | ~$222 |
| Symphony labor (4 hrs × $125) | $500 |
| **Total cost to Symphony** | **$722** |
| **Client one-time fee** | **$999** |
| **Hardware margin** | **$277 (28%)** |

### Tier 2 — Standard (Mac Mini M2 8GB)

| Item | Cost |
|---|---|
| Mac Mini M2 8GB/256GB | $599 |
| Mount + cables + accessories | $50 |
| Symphony labor (6 hrs × $125) | $750 |
| **Total cost to Symphony** | **$1,399** |
| **Client one-time fee** | **$2,250** |
| **Hardware + install margin** | **$851 (38%)** |

*First year subscription is bundled — makes the monthly feel "free" until Year 2,
improving renewal rates significantly.*

### Tier 3 — Premium (Mac Mini M4 16GB)

| Item | Cost |
|---|---|
| Mac Mini M4 16GB/256GB | $799 |
| Sonnet RackMac Mini mount | $160 |
| Symphony labor (6 hrs × $125) | $750 |
| **Total cost to Symphony** | **$1,709** |
| **Client one-time fee** | **$2,750** |
| **Margin** | **$1,041 (38%)** |

### Tier 3 Premium — Mac Mini M4 16GB/512GB (Enterprise)

| Item | Cost |
|---|---|
| Mac Mini M4 16GB/512GB | $999 |
| Rack mount + accessories | $160 |
| Symphony labor (8 hrs × $125) | $1,000 |
| **Total cost to Symphony** | **$2,159** |
| **Client one-time fee** | **$3,500** |
| **Margin** | **$1,341 (38%)** |

---

## Monthly Subscription Tiers

### Feature Comparison

| Feature | Basic ($49/mo) | Standard ($99/mo) | Premium ($199/mo) |
|---|---|---|---|
| AI chat assistant | ✓ | ✓ | ✓ |
| Knowledge base updates | Quarterly | Monthly | Weekly |
| Update trigger | Scheduled | Scheduled + on-request | On-demand (24h SLA) |
| Support response SLA | 48 hours | 24 hours | 4 hours |
| Remote monitoring (Bob) | ✓ | ✓ | ✓ |
| Conversation history backup | 30 days | 90 days | 180 days |
| Voice integration (Control4) | — | ✓ | ✓ |
| System health alerts | — | ✓ | ✓ |
| Custom AI name | ✓ | ✓ | ✓ |
| PDF manual ingestion | 1 at setup | Unlimited | Unlimited |
| ChromaDB RAG pipeline | ✓ | ✓ | ✓ |
| Dedicated tech contact | — | — | ✓ |
| Custom training data | — | — | On request |
| Multi-site/wing support | — | — | ✓ |
| Hardware tier | Budget or Standard | Standard | Premium |
| Subscription status page | — | ✓ | ✓ |

### Tier Positioning

**Basic ($49/mo)** — *Frame it as: "Your home always has the answer, even at 2am."*
- Ideal for: Vacation properties, starter packages, cost-sensitive clients
- Quarterly updates are fine for stable systems
- Still includes the full AI chat, troubleshooting, and scene guidance
- Attach to new installs under $20,000

**Standard ($99/mo)** — *Frame it as: "Every time we change something, your AI stays current."*
- Ideal for: Active families, clients who call Symphony frequently
- Voice through Control4 is a major differentiator — clients love it
- Monthly updates mean the AI reflects equipment changes quickly
- Attach to most residential installs $20,000–$75,000
- **The sweet spot tier for most clients**

**Premium ($199/mo)** — *Frame it as: "Your AI knows your home as well as we do, every week."*
- Ideal for: Large installs, estate properties, commercial, tech-forward clients
- Weekly updates mean near-real-time knowledge currency
- Dedicated tech builds a relationship with the client's AI
- Custom training data — feed in vendor-specific documentation
- Attach to installs $75,000+ and Enterprise clients

---

## Unit Economics (Subscription Only, Per Month)

| | Basic | Standard | Premium |
|---|---|---|---|
| Monthly revenue | $49 | $99 | $199 |
| Update labor cost | ~$10 (1 update/qtr ÷ 3) | ~$33 (1/mo × 30min × $65/hr) | ~$70 (4/mo × 30min × $65/hr) |
| Platform overhead | ~$5 | ~$5 | ~$10 |
| **Monthly gross margin** | **$34 (69%)** | **$61 (62%)** | **$119 (60%)** |
| **Annual gross margin** | **$408** | **$732** | **$1,428** |

*Update labor calculated at $65/hr internal cost (tech fully loaded). 
Platform overhead covers Bob server costs, Tailscale, monitoring.*

---

## Fleet Revenue Projections

### Scenario A — Conservative (20 Units, Mixed Tier)

| Tier | Units | Monthly Revenue | Monthly Gross Margin |
|---|---|---|---|
| Basic | 8 | $392 | $272 |
| Standard | 9 | $891 | $549 |
| Premium | 3 | $597 | $357 |
| **Total** | **20** | **$1,880/mo** | **$1,178/mo** |

**Annual recurring revenue: $22,560 | Annual gross profit: $14,136**

### Scenario B — Moderate (50 Units, 24 Months)

| Mix | Units | MRR | ARR |
|---|---|---|---|
| 20 Basic × $49 | 20 | $980 | $11,760 |
| 22 Standard × $99 | 22 | $2,178 | $26,136 |
| 8 Premium × $199 | 8 | $1,592 | $19,104 |
| **Totals** | **50** | **$4,750** | **$57,000** |

*Scaling from 20 → 50 requires minimal overhead; Bob handles batch updates automatically.
Marginal cost per additional unit is approximately $10–$35/month.*

### Scenario C — Aggressive (100 Units, 3 Years)

At 100 units with 40/40/20 Basic/Standard/Premium mix:
- MRR: ~$10,000
- ARR: **$120,000**
- Annual gross profit: **~$72,000**

---

## ROI Analysis

### Reduced Support Calls

Symphony currently handles approximately **4–6 "how do I...?" calls per client per year.**
These calls average 20–30 minutes of tech time and displace billable service work.

| Metric | Pre-Concierge | Post-Concierge | Improvement |
|---|---|---|---|
| Routine calls/client/year | 5 | 1.5 | 70% reduction |
| Average call time | 25 min | 25 min | — |
| Internal labor rate | $65/hr | $65/hr | — |
| Annual cost per client | $271 | $81 | **$190 saved** |

**At 30 clients:** $5,700/year saved in support labor → redirect to billable work.

### Increased Install Value

Clients with Concierge are more engaged, more confident, and more likely to expand.
Expected outcomes over 3 years:
- +15–20% client retention improvement
- $3,000–$8,000 additional LTV per client (equipment upgrades, room additions)
- 2–3 referral leads per 10 clients (Concierge is a conversation piece)

**Referral math:** 10 active clients → 2 referrals/year → at $25,000 average install → $50,000 in referred revenue annually.

### Total Value Per Client (5-Year Model)

| Revenue stream | Basic | Standard | Premium |
|---|---|---|---|
| One-time hardware/install | $999–$2,250 | $2,250 | $2,750–$3,500 |
| 5-year subscription | $2,940 | $5,940 | $11,940 |
| Support savings (reallocated) | $950 | $950 | $950 |
| Upsell/upgrade probability | Low | Medium | High |
| **5-year gross value** | **~$4,889** | **~$9,140** | **~$15,390** |

---

## Competitor Comparison

### How Symphony Concierge Compares

| Feature | Symphony Concierge | Control4 AI (Josh.ai integration) | Savant AI | Crestron Pyng |
|---|---|---|---|---|
| Private/local AI | **✓ 100% local** | ✗ Cloud (AWS) | ✗ Cloud | ✗ Cloud |
| Data privacy | **No data leaves home** | Conversations sent to cloud | Conversations to cloud | Cloud processed |
| Works offline | **✓ Full function** | ✗ Internet required | ✗ Internet required | Limited |
| Custom knowledge (your home) | **✓ Per-room, per-device** | Generic + voice commands | Voice commands only | None |
| Troubleshooting guidance | **✓ Device-specific** | ✗ Basic | ✗ None | ✗ None |
| Monthly cost | **$49–$199** | $199/mo (Josh.ai) + C4 dealer fee | ~$150–$300/mo via dealer | Included in Pyng |
| Hardware required | **$200–$800** | Josh micro ($299) | Savant Remote ($449) | Crestron processor |
| Integrator dependency | **Symphony only** | Any C4 dealer | Savant dealers only | Crestron dealers only |
| Model upgradable | **✓ Swap Ollama model** | ✗ Vendor controlled | ✗ Vendor controlled | ✗ Vendor controlled |
| RAG / document ingestion | **✓ PDFs + project data** | ✗ No | ✗ No | ✗ No |
| WebSocket real-time streaming | **✓** | ✗ | ✗ | ✗ |

### Josh.ai (Primary Voice AI Competitor)

**Josh.ai** is the leading voice AI for smart homes, integrated with Control4, Lutron,
Crestron, and others. It's a strong product — but it's cloud-based.

**Where Symphony Concierge wins:**
- Privacy: Josh.ai sends every voice command to their cloud servers
- Cost: Josh.ai is $199/month minimum; Symphony Concierge is $49/month
- Depth: Josh.ai handles voice commands; Concierge handles *conversations and troubleshooting*
- Independence: Josh.ai shutting down would break the system; Concierge keeps working forever

**Where Josh.ai wins:**
- Voice first: Josh.ai is purpose-built for voice; Concierge is chat-first
- Integrations: Josh.ai integrates with 100+ smart home platforms
- Natural language device control: Josh.ai can actually control devices; Concierge advises

**Positioning:** These products are complementary. Symphony can sell both — Josh.ai for voice control, Concierge for knowledge/troubleshooting. But if the client must choose one, Concierge is more differentiated.

### Competitive Objection Handling

**"Control4 has its own AI/voice features."**
> "Control4's AI features are basic and cloud-dependent. They know nothing specific about your home. Aria knows your exact equipment, your rooms, your scenes — and every conversation stays in your house."

**"We already pay for a service contract with [Dealer]."**
> "Service contracts cover physical service visits. Aria is your 24/7 first line of support — she answers your questions at 2am, walks you through troubleshooting, and tells you exactly what to tell us when you do call. Most clients find they call us for real problems, not 'how do I...?' questions."

**"I can just ask ChatGPT about my Control4."**
> "ChatGPT knows Control4 in general, but it doesn't know your system. It doesn't know that your 'Movie Time' scene lowers a Sony VPL-XW5000 projector with a 130-inch Screen Innovations screen. Aria knows your exact house. Try asking ChatGPT which input your Apple TV is on — it can't answer that."

**"Is this a monthly fee forever?"**
> "Yes, like any service subscription. The value is that Aria stays current as your system evolves. If you ever cancel, the appliance keeps working with the last knowledge base we installed — it just won't update when you add equipment."

---

## Pricing Presentation: How to Sell It

### In a New Install Proposal

Add as a line item:

```
Symphony Concierge AI Appliance
  Hardware (Mac Mini M4 16GB)         $2,750 installed
  Annual service (first year included)    —
  Starting Month 13: $99/month
```

This positions Concierge as a premium add-on with clear ongoing value.

### In a Service Visit Upsell

Script for the technician:

> "We've been working on your system for a couple years now, and I know you call us when things feel confusing. We just launched a new service — it's like having a 24/7 tech who knows your exact house sitting in your AV rack. Every conversation stays private in your home. Want me to show you a demo on my phone?"

### Leave-Behind

Print the **Getting Started Guide** generated by `client_onboarding.py` and leave it with the client after installation. It's personalized to their rooms and scenes — they immediately see the value.

---

## Go-to-Market Phases

### Phase 1 — Closed Beta (Months 1–3)
- Install on 3 trusted clients at no cost (use as beta testers)
- Gather real usage data and testimonials
- Refine knowledge builder and UI

### Phase 2 — Existing Client Upsell (Months 4–12)
- Offer to all existing clients at next service visit
- Add to proposal templates as a standard line item
- Feature in Symphony newsletter
- Target: 15–20 installs

### Phase 3 — New Install Standard (Months 13+)
- Bundle into all new proposals above $15,000
- 3-month free trial → then monthly
- Referral program: 1 free month per referred install that converts
- Target: 30–50 active units by end of Year 2

---

## Revenue Forecast — First 24 Months

| Period | New Units | Fleet Size | MRR | ARR Run Rate |
|---|---|---|---|---|
| Months 1–3 | 3 (beta) | 3 | $0 | — |
| Months 4–6 | 5 | 8 | $545 | $6,540 |
| Months 7–12 | 10 | 18 | $1,265 | $15,180 |
| Months 13–18 | 12 | 30 | $2,190 | $26,280 |
| Months 19–24 | 10 | 40 | $2,980 | $35,760 |

*Assumptions: 50% Basic, 35% Standard, 15% Premium. 3% monthly churn (industry-typical for recurring service.*
*Churn management: annual check-in call + knowledge update reminder keeps churn low.*

---

## Pricing Objections & Responses

| Objection | Response |
|---|---|
| "Too expensive for hardware" | "It's less than a Control4 T4 touch panel, and it works for the whole house 24/7. The first year subscription is included." |
| "Why can't I just use my phone?" | "You can — that's exactly how most people use it. The AI runs in your house on this small computer. Your phone just connects to it." |
| "What if you go out of business?" | "The appliance keeps working forever. The software is open-source (Ollama, ChromaDB). Symphony maintains it, but it's not dependent on us." |
| "$99/month feels like a lot" | "It's $3.30 a day for a 24/7 tech who knows your exact house. One avoided service call ($250+) covers 2.5 months of subscription." |
| "Can I pause my subscription?" | "We offer a pause (no updates, just monitoring) at $25/month for vacation periods. Full pause available for seasonal clients." |

---

*Symphony Smart Homes — Pricing Model v2.0 | Internal Document | Not for Distribution*
*Questions: Engineering team via Bob*
