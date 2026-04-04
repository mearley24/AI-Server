# SymphonySH.com — Upgrade to Convert

## Current State
The site looks premium — dark cinematic aesthetic, real photography, strong copy, Vail Valley positioning. The foundation is excellent. This prompt adds the missing pieces that turn visitors into clients.

## 1. Social Proof — Testimonials Section

Add a testimonials section between "Our Process" and "Why Us" on the homepage:

### Option A: Google Reviews Widget
If a Google Business Profile exists, embed a reviews widget. Check if there's a Google Place ID in .env or config.

### Option B: Static Testimonials
Create 3-4 testimonial cards. Use this format:
```
"Quote from client about their experience."
— First Name L., Location (e.g., Beaver Creek)
Project type (e.g., Whole-Home Audio & Automation)
```

Design: dark cards matching the site aesthetic. Gold/warm accent for quote marks. Client first name + last initial only. No photos needed — the luxury market values privacy.

If no real testimonials are available yet, create a `src/components/Testimonials.tsx` component with placeholder data that's easy to swap later. Add a comment: `// TODO: Replace with real client testimonials`

Also add a subtle "Google Reviews" or "5-star rated" badge near the hero CTAs if applicable.

## 2. About Page — Add the Human Element

The `/about` page reads like a philosophy page. Add:

### Founder Section
```
About the Founder

Matt Earley started Symphony Smart Homes after years in the AV integration industry, 
driven by a simple frustration: clients deserved better. Better communication, better 
craftsmanship, and systems that actually work after the installer leaves.

Based in Eagle County, Matt personally oversees every project from first walkthrough 
to final programming. When you call Symphony, you talk to the person doing the work.
```

Design: clean text section, no photo needed unless one exists. Keep the same dark aesthetic.

### By the Numbers (if data is available)
Subtle stats row:
- Years in Vail Valley
- Projects completed
- 5-star reviews

If exact numbers aren't available, skip this — never use fake stats.

## 3. Project Case Studies

The `/projects` page has photo categories but no context. Add case study cards:

For each project category (Home Theater, Mounted TVs, Wiring), add a brief case study format:

```
[Project Photo]
The Challenge: Client needed a home theater in an existing basement with limited ceiling height.
The Solution: Custom short-throw projector setup with in-wall speakers and acoustic treatment.
The Result: "We use it every night." — Client, Edwards
```

This gives the photos meaning and demonstrates problem-solving ability.

If specific project details aren't available, at least add descriptive captions to the photo galleries instead of bare images.

## 4. Service Pages — Add Pricing Signals

The FAQ mentions "transparent pricing" but the site has no pricing signals. Add to each service page:

```
Projects typically start at $X,XXX for [basic scope].
Every home is different — schedule a walkthrough for an accurate quote.
```

Rough ranges to use (adjust to what's accurate):
- Pre-wire: "Starting at $3,000 for new construction"
- Installation: "Starting at $5,000 for whole-home control"
- Maintenance: "Service calls from $150/hour"
- Matterport: "Starting at $500 per scan"

This sets expectations and filters out budget-mismatch leads. Add as a subtle callout on each service page, not a full pricing table.

## 5. SEO Improvements

### Meta Tags
Check that every page has unique:
- `<title>` — include "Vail Valley" and the service name
- `<meta name="description">` — 150 chars, include location + service
- Open Graph tags for social sharing

### Schema Markup
Add JSON-LD structured data to `index.html` or via the SEO component:
```json
{
  "@context": "https://schema.org",
  "@type": "LocalBusiness",
  "name": "Symphony Smart Homes",
  "description": "Smart home integration in Vail Valley & Eagle County",
  "telephone": "(970) 519-3013",
  "email": "info@symphonysh.com",
  "address": {
    "@type": "PostalAddress",
    "addressLocality": "Eagle",
    "addressRegion": "CO",
    "addressCountry": "US"
  },
  "areaServed": ["Vail", "Beaver Creek", "Edwards", "Avon", "Eagle"],
  "serviceType": ["Smart Home Installation", "Home Automation", "AV Integration", "Pre-Wire", "Matterport 3D Scanning"]
}
```

### Sitemap
Check that `public/sitemap.xml` includes ALL actual pages:
- `/`, `/services`, `/about`, `/contact`, `/projects`, `/matterport`
- `/services/prewire`, `/services/automation`, `/services/audio`, `/services/lighting`, etc.
- `/walkthrough`, `/privacy`, `/terms`

## 6. Footer Copyright Fix
Homepage shows © 2026, service pages show © 2024. Make it dynamic:
```tsx
© {new Date().getFullYear()} Symphony Smart Homes
```

## 7. 404 Page
`/pre-wiring`, `/installation`, `/maintenance`, `/3d-tours`, `/portfolio` all 404. Either:
- Add redirects to the correct URLs (preferred)
- Or improve the 404 page with links to main sections

In the router (App.tsx or wherever routes are defined), add redirects:
```
/pre-wiring → /services/prewire
/installation → /install  
/maintenance → /troubleshooting
/3d-tours → /matterport
/portfolio → /projects
```

## 8. Performance & Polish

### Loading
- Add a subtle page transition animation (fade-in on route change)
- Lazy-load images below the fold
- Add `loading="lazy"` to all `<img>` tags not in the hero

### Interactive Elements
- The "Schedule a Walkthrough" CTA — make sure it goes to a real booking flow or contact form, not just a mailto
- Add a floating phone button on mobile (fixed bottom-right, click-to-call)
- Smooth scroll anchors for homepage sections

### Favicon
Verify the favicon is the Symphony S logo, not a default Vite icon.

## 9. Analytics
If not already present, add:
- Google Analytics 4 (or Plausible for privacy-first analytics)
- Google Search Console verification meta tag
- Facebook Pixel (if running any ads)

Check `.env` for any existing analytics IDs before adding.

## 10. Content Additions for SEO

### Blog / Resources Section (Future)
Create a placeholder `/resources` or `/blog` page that can hold:
- "What to Know About Pre-Wiring Your New Build"
- "Control4 vs Josh.ai: Which Smart Home System is Right for You?"
- "How Much Does a Smart Home Cost in Vail Valley?"

These pages would rank for local search queries. Don't write the full articles now — just create the page template and route so it's ready to populate.

## Build & Deploy
```bash
npm run build
# or
bun run build
```

Then push to GitHub — the site appears to deploy via GitHub Pages.
