# Technical Writing — Sector Playbook

**Tier:** 1 (High Skill, Good Pay)  
**Avg Task Value:** $75–400  
**Target Platforms:** Upwork, Toptal, Direct (software companies)  
**Bob's Role:** Technical documentation specialist for software, APIs, and systems  

---

## Sector Overview

Technical writing is one of Bob's highest-fit Tier 1 sectors. The combination of API familiarity, smart home/AV documentation experience, and structured output capability makes Bob a strong technical writer for:
- Software documentation (READMEs, user guides, admin guides)
- API documentation (endpoint references, integration guides)
- Developer guides and SDK documentation
- System administration guides
- Smart home / IoT product documentation
- Runbooks and SOPs for technical teams

**Rate potential:** $0.10–0.25/word or $75–150/hr. A strong technical writer on Upwork earns $100–400 per document.

---

## Document Types

### 1. README / Project Documentation
**What it looks like:**
- "Write a README for this GitHub project"
- "Create documentation for this Python library"
- "Document this CLI tool"

**Standard README structure:**
```markdown
# Project Name

One-line description of what this does.

## Features
- Feature 1
- Feature 2
- Feature 3

## Requirements
- Python 3.9+
- [Other dependencies]

## Installation

```bash
pip install package-name
```

## Quick Start

```python
from package import main_class
# Minimal working example
```

## Configuration

| Variable | Description | Default |
|----------|-------------|----------|
| `SETTING_1` | What it controls | `value` |

## Usage

### Basic Usage
[Most common use case]

### Advanced Usage
[More complex patterns]

## API Reference
[Link to full API docs or inline if small]

## Contributing
[How to submit issues and PRs]

## License
[License type]
```

**Time estimate:** 30–60 minutes for a typical library README  
**Rate target:** $75–200

---

### 2. API Documentation
**What it looks like:**
- "Document these 20 REST API endpoints"
- "Write an integration guide for our API"
- "Create developer onboarding docs for our platform"

**Endpoint documentation template:**
```markdown
## POST /api/v1/resource

Create a new resource.

**Authentication:** Bearer token required

**Request Headers:**
| Header | Value |
|--------|-------|
| `Authorization` | `Bearer {token}` |
| `Content-Type` | `application/json` |

**Request Body:**
```json
{
  "field_name": "string",      // Required. Description.
  "optional_field": "string"   // Optional. Description. Default: null
}
```

**Success Response (201 Created):**
```json
{
  "id": "uuid",
  "field_name": "string",
  "created_at": "2026-02-27T00:00:00Z"
}
```

**Error Responses:**
| Code | Meaning | When it occurs |
|------|---------|----------------|
| 400 | Bad Request | Missing required field |
| 401 | Unauthorized | Invalid or missing token |
| 409 | Conflict | Resource already exists |
| 500 | Server Error | Internal error |

**Example (curl):**
```bash
curl -X POST https://api.example.com/v1/resource \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"field_name": "value"}'
```
```

**Integration guide structure:**
```
1. Getting Started
   - Authentication (how to get and use API keys)
   - Base URL and versioning
   - Rate limits

2. Core Concepts
   - Resource model (what objects exist)
   - Lifecycle of key resources

3. Common Use Cases
   - Step-by-step for 2–3 most common integrations
   - Code samples in 1–2 languages

4. Error Handling
   - Error code reference
   - Retry strategies
   - Webhooks (if applicable)

5. API Reference
   - Grouped by resource
   - Each endpoint documented per template above

6. Changelog
```

**Time estimate:** 10–15 minutes per endpoint; 60–120 minutes for an integration guide  
**Rate target:** $10–25 per endpoint; $150–400 for a full integration guide

---

### 3. User Guides and Manuals
**What it looks like:**
- "Write a user manual for this software product"
- "Create an admin guide for our platform"
- "Document how to use this IoT device"

**Standard structure:**
```
1. Introduction
   - What the product does
   - Who this guide is for
   - How to use this guide

2. Getting Started
   - System requirements
   - Installation / account setup
   - First-time configuration
   - Your first [task]

3. Core Features
   [One section per major feature]
   - What it does
   - How to use it
   - Configuration options
   - Tips and best practices

4. Administration (if applicable)
   - User management
   - Settings and configuration
   - Backup and recovery

5. Troubleshooting
   - Common issues and solutions
   - Error message reference
   - Getting help

6. Reference
   - Keyboard shortcuts
   - Glossary
   - Technical specifications
```

**Time estimate:** 60–180 minutes for a comprehensive user guide  
**Rate target:** $150–400

---

### 4. Runbooks and SOPs
**What it looks like:**
- "Document our deployment process"
- "Create an incident response runbook"
- "Write SOPs for our onboarding process"

**Runbook structure:**
```markdown
# [Process Name] Runbook

**Owner:** [Team/Role]
**Last Updated:** [Date]
**Version:** [X.Y]

## Overview
[What this runbook covers, when to use it]

## Prerequisites
- [ ] Access to [system]
- [ ] [Tool] installed
- [ ] [Permission] granted

## Procedure

### Step 1: [Title]
1. [Specific action]
2. [Next action]

**Expected output:**
```
[What you should see]
```

**If you see an error:**
[What to do]

### Step 2: [Title]
...

## Rollback Procedure
[How to undo this procedure if something goes wrong]

## Verification
[ ] [Check 1]: Expected result
[ ] [Check 2]: Expected result

## Escalation
If you cannot complete this runbook within [timeframe], escalate to [contact].
```

**Time estimate:** 30–60 minutes per runbook  
**Rate target:** $75–200

---

## Writing Quality Standards for Technical Docs

### The technical writer's cardinal rules:
1. **Accuracy first.** A wrong instruction is worse than no instruction.
2. **Test the examples.** Every code example should be verifiable.
3. **Write for the reader's knowledge level.** Know your audience.
4. **Numbered steps for procedures.** Never use bullets for sequential actions.
5. **Consistent terminology.** Pick one word for each concept and use it everywhere.
6. **Screenshots are worth 1,000 words.** But placeholder notes work fine: "[SCREENSHOT: Settings page]"

### Quality checklist:
- [ ] All code examples syntactically correct
- [ ] All steps tested and verified against actual product behavior
- [ ] Consistent terminology throughout
- [ ] Structure follows standard template for document type
- [ ] Version/date included
- [ ] Placeholder notes for missing content (never omit a section without noting it)

---

## Platform Strategy

### Upwork
- Title: "Technical Writer | API Docs | User Guides | Software Documentation"
- Portfolio: Sample API endpoint reference, sample README, sample user guide section
- Target: $60–100/hr or $0.12–0.20/word for documentation projects
- Niche: IoT/smart home tech, developer tools, SaaS platforms

### Direct Client Outreach
- Target: early-stage startups with undocumented APIs (common and urgent need)
- Offer: "API documentation package" — full endpoint reference for a flat fee ($500–1,500)
- Value prop: developers are 3–4× more productive with good API docs; reduces support burden

---

## Quality Checklist

| Element | Standard |
|---------|----------|
| Code examples | All tested and syntactically correct |
| Numbered steps | All sequential procedures use numbered lists |
| Consistent terms | Same word for same concept throughout |
| Completeness | No empty sections; placeholders for WIP |
| Version/date | Always present in document header |
| Cross-references | Internal links to related docs where relevant |
