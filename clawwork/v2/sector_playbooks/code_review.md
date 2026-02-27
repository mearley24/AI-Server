# Code Review — Sector Playbook

**Tier:** 1 (High Value, High Skill)  
**Avg Task Value:** $100–500  
**Target Platforms:** Codementor, Upwork, GitHub Sponsors (direct)  
**Bob's Role:** Technical reviewer, bug finder, architectural advisor  

---

## Sector Overview

Code review is one of the highest-value ClawWork sectors on a per-hour basis. Developers pay $80–150/hr for expert code review, and a focused 45-minute session can produce a $100–200 deliverable. Bob's system integration background, Python proficiency, and architecture pattern recognition make this a strong fit.

**Bob's technical strengths:**
- Python (primary)
- JavaScript/Node.js (secondary)
- REST API design and review
- Automation and scripting (bash, cron, systemd)
- Smart home / IoT integration patterns
- Database design (SQLite, PostgreSQL basics)
- Security: authentication flows, secret management, injection prevention

---

## Review Types

### 1. Full Code Review
**What it looks like:**
- "Review my Python Flask API — looking for bugs, security issues, and improvements"
- "Code review this Node.js backend before we go to production"
- "Review my automation script — is it production-ready?"

**Standard deliverable:**
```markdown
# Code Review: [Project Name]
**Reviewer:** Bob (ClawWork)
**Date:** [Date]
**Files reviewed:** [list]
**Lines of code:** [estimate]

## Executive Summary
[2–3 sentence overall assessment: ready/not ready, main concern, main strength]

## Critical Issues (must fix before production)
[Each issue gets:]
- **File:** path/to/file.py, Line: X–Y
- **Issue:** Description
- **Risk:** What breaks or what attack vector this enables
- **Fix:** Specific code change or approach

## Major Issues (should fix soon)
[Same format]

## Minor Issues (nice to have)
[Same format, but brief]

## Security Review
- Authentication: [assessment]
- Input validation: [assessment]
- Secret management: [assessment]
- Dependencies: [assessment — any known CVEs in requirements?]

## Architecture Notes
- [1–3 architectural observations, positive or constructive]

## What's Working Well
- [2–3 genuine positives — never skip this section]

## Recommended Next Steps
1. Fix critical issues
2. ...
```

**Time estimate:** 30–60 minutes for codebases up to 500 lines  
**Rate target:** $100–300

---

### 2. Security Audit
**What it looks like:**
- "Audit this authentication system for vulnerabilities"
- "Review our API for common security issues"
- "Check our environment variable handling and secret management"

**Security checklist:**

**Authentication & Authorization:**
- [ ] Passwords hashed with bcrypt/argon2 (not MD5, SHA1)
- [ ] JWTs: algorithm explicitly set (not 'none'), expiry enforced
- [ ] Session tokens: sufficient entropy, secure cookie flags
- [ ] Authorization: every endpoint checks permissions (no IDOR)
- [ ] Rate limiting on login and sensitive endpoints

**Input Validation:**
- [ ] All user input validated before use
- [ ] SQL: parameterized queries only (no string concatenation)
- [ ] No eval() or exec() on user input
- [ ] File uploads: type checking, size limits, path traversal prevention

**Secrets & Configuration:**
- [ ] No hardcoded credentials in source code
- [ ] Environment variables used for all secrets
- [ ] .env file not committed (check .gitignore)
- [ ] API keys scoped to minimum required permissions

**Dependencies:**
- [ ] requirements.txt / package.json present and pinned
- [ ] Check for known CVEs (pip audit, npm audit)
- [ ] No wildcard version specs in production deps

**Error Handling:**
- [ ] Stack traces not exposed to end users
- [ ] Logging captures errors without logging sensitive data
- [ ] Graceful handling of all external API failures

**Time estimate:** 30–45 minutes  
**Rate target:** $100–250

---

### 3. Architecture Review
**What it looks like:**
- "Is this system design scalable?"
- "Review our microservices architecture"
- "Should we be using this database for this use case?"

**Structure:**
```markdown
# Architecture Review: [System Name]

## System Overview
[Brief description of what was reviewed]

## Architecture Assessment
### Scalability
[Assessment of horizontal/vertical scaling characteristics]

### Maintainability
[Code organization, documentation, naming conventions]

### Reliability
[Error handling, retry logic, failure modes]

### Operational Concerns
[Monitoring, alerting, deployment complexity]

## Recommendations
[Prioritized list with rationale]

## Red Flags
[Anything that needs immediate attention]
```

**Time estimate:** 30–60 minutes  
**Rate target:** $150–400

---

### 4. Bug Hunt
**What it looks like:**
- "My Python script crashes randomly — find the bug"
- "This function returns wrong results sometimes — why?"
- "Help me debug this race condition"

**Bob's approach:**
1. Read the error message / symptom description carefully
2. Identify the minimal code section involved
3. Trace the execution path for the failure case
4. Look for: off-by-one errors, None/null handling, race conditions, encoding issues, float precision
5. Write a minimal reproducible test case
6. Provide the fix with explanation

**Time estimate:** 15–45 minutes  
**Rate target:** $50–150 flat fee (not hourly)

---

## Codementor-Specific Tactics

Codementor is the primary platform for code review. Key tactics:

### Profile Setup
- Headline: "Python & API Expert | Code Reviews | System Integration | Security Audits"
- Rate: $60–120/hr (start at $65, raise after 5 reviews)
- Specialties listed: Python, REST APIs, automation, smart home/IoT, SQLite
- Response time: < 5 minutes (Codementor heavily weights responsiveness)

### Review Request Response Template
```
Hi [name] — I've reviewed your request and I can help with this.

I specialize in [relevant skill from their request]. For this type of review,
I'll cover: [2–3 specific things you'll look at].

Estimated time: [X–Y minutes].
Deliverable: [written report / annotated code / screen share review]

Ready when you are.
```

### During the Review
1. Start by reading the README and running the code (if possible)
2. Note your first impressions — they're often the most important
3. Work systematically: imports → configuration → data models → business logic → API layer → tests
4. Annotate as you go; don't try to hold everything in memory
5. Finish with a genuine positive comment — every codebase has something done well

---

## Review Quality Standards

| Element | Requirement |
|---------|-------------|
| Critical issues | All must be identified; none missed |
| Security checklist | Always completed for API/backend reviews |
| Positives included | Minimum 2 genuine positives in every review |
| Fix suggestions | Every issue must include a suggested fix |
| Code examples | Provide corrected code snippets for critical issues |
| Tone | Professional, helpful, never condescending |
| Response time | < 1 hour for async reviews on Codementor |

---

## When to Decline

- Codebases > 2,000 lines if asking for "complete" review in <2 hours (scope is unrealistic)
- Languages outside Bob's competency: Java, C/C++, iOS/Android native, Rust
- Tasks where the client's codebase is >10,000 lines and they expect full understanding in a session
