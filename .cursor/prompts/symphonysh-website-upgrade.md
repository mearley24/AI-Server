# SymphonySH.com — Targeted Upgrades

## Context
symphonysh.com is a React + Vite + shadcn/ui site. Repo: `mearley24/symphonysh`. Deploys via Cloudflare Pages from GitHub. DNS on Cloudflare, www is primary, apex 301s to www.

### Already Done (DO NOT redo):
- SEO structured data via `src/constants/businessSchema.ts` — LocalBusiness JSON-LD with NAP, geo, hours, service types
- Zapier webhook centralized in `src/constants/zapier.ts` for scheduling flow
- Homepage FAQ with human-style copy
- Anti-AI tone polish on homepage
- Transparent header, CTA routing
- `sameAs` field documented and left empty (waiting for real profile URLs)
- `hasMap` Google Maps link added
- Cloudflare Pages build config fixed (Vite build, dist output)

### DO NOT add:
- Google Analytics, Facebook Pixel, or any new third-party tracking scripts
- New schema markup — `businessSchema.ts` already handles this
- Blog/resources placeholder pages — not needed yet
- Any pricing information on service pages — Matt will add this when ready

---

## 1. Social Proof — Testimonials Component

Create `src/components/Testimonials.tsx`:
- Place it on the homepage between "Our Process" and "Why Us" sections
- 3 testimonial cards, placeholder data with clear `// TODO: Replace with real client testimonials` comments
- Design: dark cards matching existing aesthetic (use existing Tailwind/shadcn tokens from the site), gold/warm accent for quote marks
- Format per card: quote text, client first name + last initial, location (e.g., Beaver Creek), project type
- No photos — privacy-first for the luxury market
- Responsive: 3 cols desktop, 1 col mobile

Use placeholder testimonials that sound realistic for a Vail Valley smart home integrator — DO NOT make them sound AI-generated. Keep them short (1-2 sentences max).

## 2. About Page — Founder Section

Edit `src/pages/About.tsx`:
- Add a "Meet the Founder" section after the existing "How We Work" content
- Copy:
```
Matt Earley started Symphony Smart Homes after years in the AV integration industry, 
driven by a simple frustration — clients deserved better. Better communication, better 
craftsmanship, and systems that actually work after the installer leaves.

Based in Eagle County, Matt personally oversees every project from first walkthrough 
to final programming. When you call Symphony, you talk to the person doing the work.
```
- Design: clean text section, no photo, same dark aesthetic as the rest of the page
- Do NOT add a stats row (no fake numbers)

## 3. Project Case Study Captions

Edit the `/projects` page and photo gallery components:
- Add descriptive captions to each photo category card (Home Theater, Mounted TVs, Wiring & Infrastructure)
- Each card should have a 1-2 sentence description of what the category involves, e.g.:
  - Home Theater: "From dedicated theater rooms with acoustic treatment to casual media spaces — designed for how you actually watch."
  - Mounted TVs: "Clean, level installs with hidden wiring. Every mount rated for the TV, every cable managed."
  - Wiring & Infrastructure: "The work behind the walls that makes everything else possible. Cat6, HDMI, speaker wire, conduit — done right the first time."
- Check the photo gallery sub-pages (`/photos/*`) — if they're empty or thin, note it in a TODO comment

## 4. URL Redirects

In the router (check `src/App.tsx` or wherever routes are defined), add `<Navigate>` redirects for common mistyped/old URLs:
```tsx
<Route path="/pre-wiring" element={<Navigate to="/services/prewire" replace />} />
<Route path="/installation" element={<Navigate to="/install" replace />} />
<Route path="/maintenance" element={<Navigate to="/troubleshooting" replace />} />
<Route path="/3d-tours" element={<Navigate to="/matterport" replace />} />
<Route path="/portfolio" element={<Navigate to="/projects" replace />} />
```

## 5. Footer Copyright — Dynamic Year

Find the Footer component (`src/components/Footer.tsx`). If any copyright text is hardcoded to a year, replace with:
```tsx
© {new Date().getFullYear()} Symphony Smart Homes
```

Check ALL footer instances — homepage footer and service page footers may be different components.

## 6. Mobile Polish

- Add a floating click-to-call phone button on mobile (visible below 768px):
  - Fixed position, bottom-right, 56px circle
  - Phone icon, links to `tel:+19705193013`
  - Match the site's gold CTA color
  - Only visible on mobile (hidden on desktop where phone is in header)
- Verify the "Schedule a Walkthrough" CTA routes to `/walkthrough` (the scheduling page that POSTs to Zapier)
- Add `loading="lazy"` to images below the hero fold (check all `<img>` tags across pages)

## 7. Sitemap Verification

Check `public/sitemap.xml`. Make sure it includes every real route:
- `/`, `/services`, `/about`, `/contact`, `/projects`, `/matterport`
- `/services/prewire`, `/install`, `/troubleshooting`
- `/walkthrough`, `/privacy`, `/terms`
- Service sub-pages under `/services/*` (audio, lighting, security, climate, networking, shades, maintenance)

If the sitemap is missing pages, add them. If there's no sitemap, create one.

## Build & Deploy
```bash
npm ci && npm run build
```
Commit and push to `main` — Cloudflare Pages deploys automatically.
