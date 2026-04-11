# Cline Prompt P — Full Site Audit & Polish

## Context
symphonysh.com is a React+Vite+shadcn/ui site at `~/symphonysh` (repo: `mearley24/symphonysh`). Deploys via Cloudflare Pages on push to main.

This prompt is a page-by-page audit. Every page gets reviewed for: fake content, dead links, broken flows, redundancy, and overall experience quality. The goal is that a visitor can land on ANY page and within 2 clicks understand what Symphony does, see real work, and know how to reach out. No dead ends, no cookie-cutter filler, no pages that feel like they were generated and forgotten.

Symphony's brand voice: confident but not salesy, technical but approachable, local and personal. Matt is a one-man operation with occasional crew — the site should feel premium but honest, not like a 200-person corporation.

## Ground Rules

- **NEVER create fake testimonials, fake stats, fake client names, or placeholder content that pretends to be real**
- If a section has no real data to show, remove it entirely or replace with something that IS real
- Every page must have a clear purpose and a clear next step for the visitor
- No orphan pages — every page must be reachable from the main navigation flow
- No redundant CTAs — one clear call-to-action per section, max 2 per page (schedule + call)
- The site should feel like 8-12 pages, not 50 — consolidate where it makes sense

---

## PAGE-BY-PAGE AUDIT

### 1. Homepage (`src/pages/Index.tsx`)

**Keep:**
- Hero section — strong headline, dual CTAs, location badge
- Trust strip (Local, Licensed, Full-Service, Responsive)
- Services grid (4 cards)
- How It Works (4 steps)
- Why Symphony (4 differentiators)
- FAQ accordion
- Final CTA

**Fix:**
- `<Testimonials />` — Prompt O handles this (converts to Featured Work). If Prompt O has NOT been run yet, remove the `<Testimonials />` component entirely and leave a comment: `{/* Testimonials section — add back when real client quotes are collected */}`
- `<SocialProof />` — If Prompt O has NOT been run yet: remove the TODO comments, change "150+" to "Eagle County" / "Based & operating locally", change "10+" to "Full-Service" / "Pre-wire through programming", change "Denver Metro" to "Vail Valley" / "& Eagle County". Keep "Control4 Authorized Dealer"
- Homepage service cards link to `/services/prewire`, `/install`, `/troubleshooting`, `/matterport` — but the Services hub page links to `/services/home-integration`, `/services/audio-entertainment`, etc. These are DIFFERENT sets of services. **Fix:** Make the homepage service cards link to the Services hub page (`/services`) as the primary path, with individual service pages as secondary. Change the 4 homepage cards to:
  1. "Smart Home Integration" → `/services` (the hub)
  2. "Pre-Wire & New Construction" → `/services/prewire`  
  3. "Maintenance & Support" → `/services/maintenance`
  4. "Matterport 3D Scanning" → `/matterport`
- FAQ: Review each answer — make sure pricing ranges are still accurate. The current ranges look reasonable, keep them.

### 2. Services Hub (`src/pages/Services.tsx`)

**Keep:**
- The grid of 9 service cards linking to individual service pages
- Hero section

**Fix:**
- Services hub lists 9 services, but the homepage only surfaces 4. The Services hub should be the canonical directory. Make sure the hub links match what's in the header serviceLinks array.
- Current hub service list: Home Automation, Audio & Entertainment, Smart Lighting, Shades, Climate Control, Pre-Wire, Networking, Security, Maintenance. Verify each card links to the correct `/services/xxx` route and that each route actually exists and renders.
- The hub does NOT link to Matterport. Add Matterport as the 10th card (or add a separate "Also Available" section below the main grid with Matterport and AVA remote).
- Remove any pricing signals that aren't accurate — if pricing ranges were added, verify they're in line with what Matt actually charges.

### 3. Individual Service Pages (`src/pages/services/*.tsx`)

All 9 service pages follow the same template. This is fine for consistency, but check each one:

**For ALL service pages:**
- Each page should have: Hero with service name → Capabilities grid (4 items) → Interactive demo → FAQ → CTA
- Verify the interactive demo component actually works (some may be placeholders)
- Verify FAQ answers are specific to the service, not generic copy
- Each page's "Schedule a Consultation" button should pass the correct `?service=xxx` query param to `/scheduling`
- Breadcrumb: each service page should link back to `/services`, not `/`

**Specific issues:**
- `SmartLighting.tsx` — the `LightingFixtureLibrary.tsx` component uses `/api/placeholder/200/200` for ALL fixture images. These are broken placeholder URLs. Either remove the fixture library section entirely, or replace with real fixture names and descriptions without images (just text cards). The fixture data (Lutron Caseta, RadioRA3, Ketra, etc.) is good — just kill the broken image references.
- `SmartLighting.tsx` — `TroyVoiceAssistant.tsx` has "Features coming soon:" text. Remove the "coming soon" messaging — either show what exists or remove the section.
- Check that each service page's capabilities and FAQ content is genuinely specific to that service and not copy-pasted with minor word swaps.

### 4. Projects Page (`src/pages/Projects.tsx`)

**If Prompt O has been run:** This should already be restructured into a case study hub. Verify it works correctly with project cards, filter pills, and individual project detail pages.

**If Prompt O has NOT been run:** The current page has 3 category cards (Home Theater, Mounted TVs, Wiring) linking to photo galleries. This is functional but thin. At minimum:
- Add a brief 1-2 sentence description under each category card explaining what the visitor will see
- Make sure all gallery links actually work and load photos
- Add a "Back to Our Work" breadcrumb on each photo gallery page

**Either way, verify:**
- Every gallery route in the router (`/photos/*`) actually renders and shows photos
- No 404s when clicking through the gallery hierarchy
- Photo galleries have a "Back" link to return to the projects hub
- Gallery pages are reachable from the Projects page (no orphan galleries)

### 5. About Page (`src/pages/About.tsx`)

**Review content for:**
- Does it tell Matt's story authentically? It should feel personal, not corporate
- Remove any language that implies Symphony is a large company ("our team of experts", "we have decades of experience") — be honest about being a focused local operation
- Make sure the page links to something actionable (Contact or Schedule)
- If there's a stats/numbers section, verify the numbers are real or remove them

### 6. Contact Page (`src/pages/Contact.tsx`)

**Verify:**
- Form fields: name, email, message — working form submission (check where it POSTs)
- Phone number is correct: (970) 519-3013
- Email is correct: info@symphonysh.com
- Service area mentioned: Vail Valley / Eagle County
- No duplicate contact sections (some pages have inline CTAs that compete with the Contact page)

### 7. Walkthrough Page (`src/pages/Walkthrough.tsx`)

**This page is essentially a pre-wire pricing page with 3 tiers.** Review:
- Is this the right page for the "Schedule a Walkthrough" CTA on the homepage? It feels like it should go to `/scheduling` directly, or this page should be renamed to "Pre-Wire Packages" and linked from the Pre-Wire service page instead
- **Decision:** Change the homepage "Schedule a Walkthrough" CTA to link to `/scheduling` directly. Then link this Walkthrough/packages page from the Pre-Wire service page as "View our pre-wire packages" 
- Update the Walkthrough page breadcrumb to: Home → Services → Pre-Wire → Packages
- Make sure the pricing tiers here don't conflict with any pricing mentioned on the Pre-Wire service page FAQ

### 8. AVA Page (`src/pages/Ava.tsx`)

**This is a product page for the AVA Smart Remote.** Verify:
- Is this still a product Symphony sells/recommends?
- If yes: link it from the Services hub or Home Automation service page as an add-on
- If no: remove the page and its route
- Currently it links to `https://ava.com` — verify this is the correct URL
- The page is an orphan — not linked from any nav or other page. Either connect it to the service pages or remove it.

### 9. Matterport Page (`src/pages/Matterport.tsx`)

**Verify:**
- Content is accurate for Symphony's Matterport offering
- Linked from homepage services grid (it is — good)
- Also needs to be linked from the Services hub page (currently missing)
- CTA links to `/scheduling?service=matterport-scan`

### 10. Scheduling Page (`src/pages/scheduling/`)

**Verify:**
- Form loads and renders correctly
- Service dropdown is pre-populated when arriving via `?service=xxx` query param
- All service options in the dropdown match the actual services Symphony offers
- Confirmation page (`/scheduling/confirmation`) renders after submission
- The Zapier webhook integration — check if the endpoint URL is still valid (it's in the form submission logic)

### 11. Admin Pages (`src/pages/admin/UploadMatterport.tsx`)

- This should NOT be publicly accessible. Verify it's not linked from any public page.
- If it's functional and needed, leave it. If it's a stub, remove it.

### 12. Privacy & Terms (`src/pages/Privacy.tsx`, `src/pages/Terms.tsx`)

- Verify company name is "Symphony Smart Homes" throughout
- Verify year is dynamic (`new Date().getFullYear()`)
- These are legal pages — don't modify content unless there's an obvious error

### 13. 404 Page (`src/pages/NotFound.tsx`)

- Should have a friendly message and link back to homepage
- Should list main navigation options (Services, Projects, Contact)

---

## CROSS-CUTTING ISSUES

### Navigation Flow
The nav has: Services | Projects | About | Contact + Schedule button

**Fix these flow issues:**
1. Header's "Schedule" button goes to `/scheduling` — good
2. Homepage "Schedule a Walkthrough" goes to `/walkthrough` — **change to `/scheduling`** (walkthrough is really a pre-wire packages page)
3. Every service page has "Schedule a Consultation" — these go to `/scheduling?service=xxx` — good
4. Footer only has Privacy/Terms — **add Services, Our Work, About, Contact links to footer**

### Redundant Pages
These routes all point to the same components:
- `/install` and `/services/home-integration` → same `HomeIntegration` component
- `/troubleshooting` and `/services/maintenance` → same `Maintenance` component
- `/networking` and `/services/networking` → same `Networking` component

**Fix:** Keep the `/services/*` routes as canonical. Change `/install`, `/troubleshooting`, `/networking` to `<Navigate>` redirects (some already are — verify all of them). Update any links pointing to the short URLs to use the `/services/*` versions instead.

### Footer Enhancement
The current footer (`src/components/Footer.tsx`) is minimal — just copyright + Privacy/Terms. **Expand it:**

```tsx
// Three columns:
// Col 1: Logo + tagline + phone
// Col 2: Quick Links — Services, Our Work, About, Contact, Schedule
// Col 3: Service Areas — Vail, Beaver Creek, Edwards, Avon, Eagle, Minturn
// Bottom: Copyright (dynamic year) + Privacy + Terms
```

Note: The homepage (`Index.tsx`) has its OWN inline footer that's more complete than the shared `Footer.tsx` component. **Consolidate:** Make the shared Footer component match the homepage footer design, then use it everywhere. Remove the inline footer from Index.tsx.

### Placeholder Image Cleanup
- `LightingFixtureLibrary.tsx`: 6 fixture images point to `/api/placeholder/200/200` — broken. Replace with simple text cards or remove the image property entirely and render the fixture data as text-only cards.
- Verify no other components use placeholder image URLs.

### SEO Consistency
Every page should have:
- Unique `<title>` including "Vail Valley" or "Eagle County" + service name
- Unique `<meta description>` under 160 chars
- Schema markup where applicable (local business, service, FAQ)
- The SEO component is already used on most pages — verify ALL pages use it

### Mobile Responsiveness
Verify on 375px width:
- Header hamburger menu opens and closes correctly
- All nav links work in mobile menu
- Service cards stack to single column
- Photo galleries are touch-friendly
- CTAs are full-width and tap-friendly on mobile
- No horizontal scroll on any page

---

## DO NOT

- Add any fake testimonials, reviews, or client quotes
- Add any placeholder stats or made-up numbers
- Install new npm packages
- Change the color scheme, fonts, or design system
- Remove any existing photo gallery pages or photos
- Touch anything outside the symphonysh repo

## BUILD & DEPLOY

```zsh
cd ~/symphonysh
npm run build
```

Fix ALL TypeScript errors and warnings. Then:

```zsh
git add -A
git commit -m "Full site audit: fix dead links, kill placeholders, consolidate footer, improve flow"
git push origin main
```

Cloudflare Pages auto-deploys.

## VERIFICATION CHECKLIST

After build succeeds, click through every route and verify:

1. Homepage: no fake content, services link to correct pages, CTAs go to /scheduling
2. /services: all 9+ service cards link to working pages
3. Each /services/xxx: demo works, FAQ is specific, CTA passes correct service param
4. /projects: shows real work, galleries load, back links work
5. /about: honest content, links to contact/schedule
6. /contact: form works, correct phone/email
7. /matterport: content is accurate, linked from services hub
8. /scheduling: form loads, service dropdown works, ?service= prefills correctly
9. /walkthrough: linked from pre-wire page, not from homepage hero
10. Footer: consistent across all pages, includes nav links
11. Mobile: hamburger menu, stacked layout, no horizontal scroll
12. No console errors on any page
13. No TODO comments visible in rendered output (code comments are fine)
14. Search `placeholder` in all .tsx files — no broken placeholder URLs remain
15. Every page has functioning "back" navigation or breadcrumb
