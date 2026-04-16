# Cline Prompt: Website Polish — Make It POP

**Repo:** `mearley24/symphonysh` (React + Vite + Tailwind + shadcn/ui, Cloudflare Pages)
**Goal:** Visual polish + structural improvements to make symphonysh.com stand out and convert visitors into leads. Do NOT break existing functionality. Commit and push when done.

---

## IMPORTANT RULES
- Test `npm run build` after changes to ensure zero errors
- Keep the existing dark premium aesthetic (black bg, gold accent `#ca9f5c`)
- Do NOT remove any existing pages or routes
- Keep all existing service pages, scheduling, Matterport, Ava, photo galleries
- Fonts: Barlow Condensed (headings) + Inter (body) — already loaded
- Accent color: `#ca9f5c` (gold) — keep this, it's the brand

---

## 1. STICKY NAV UPGRADE (Header.tsx)

The current nav has an unconventional placement — the "Menu" button floats in the middle of the page when not scrolled. Fix this:

**When NOT scrolled (top of page):**
- Show the large logo centered at top (keep current behavior)
- Move the Menu button to top-right corner, fixed position, always visible
- Add a subtle pill-shaped background: `bg-white/5 backdrop-blur-sm border border-white/10 rounded-full px-4 py-2`

**When scrolled:**
- Keep current behavior (logo shrinks, nav bar appears) — it's good
- Ensure the transition is smooth (already has duration-500)

**Additional nav improvements:**
- Add a "Schedule" CTA button in the scrolled header bar (right side, accent colored, small)
- Add social links in the overlay menu (bottom): Instagram, Google Business link (use simple icon placeholders for now — `Globe` and `Camera` from lucide-react)

---

## 2. HERO SECTION ENHANCEMENTS (Index.tsx)

Make the hero section hit harder:

**Add a subtle animated gradient overlay:**
- Below the hero text, add a slow-moving radial gradient that pulses (the existing `animate-[pulse_6s...]` blob is good — add a second one on the left side with a slight delay)

**Add a "scroll indicator" at the bottom of the hero:**
- Small animated chevron-down icon between the CTA buttons and trust strip
- Use `animate-bounce` with reduced intensity: `opacity-40`
- Only show on desktop (hidden on mobile)

**Trust strip enhancement:**
- Add real numbers where possible:
  - "Local" → "10+ Years" (or keep "Local" but add "Est. 2015" or similar — Matt can update the year)
  - "Licensed" → keep as is
  - "Full-Service" → keep as is  
  - "Responsive" → "Same-Day Response" (stronger claim)

---

## 3. ADD TESTIMONIALS SECTION (new component or update Testimonials.tsx)

The current `Testimonials.tsx` actually shows "Featured Projects" — not testimonials. This is fine, keep it.

**Add a NEW actual testimonials section** between "How It Works" and "Featured Projects":

Create `src/components/ClientTestimonials.tsx`:

```tsx
// Placeholder testimonials — Matt will replace with real ones
const testimonials = [
  {
    quote: "Matt handled everything from pre-wire to final programming. One guy, one phone call, zero runaround. Our system just works.",
    author: "Homeowner",
    location: "Beaver Creek, CO",
  },
  {
    quote: "We've used other integrators in the valley. Symphony is the only one that picks up the phone and actually shows up when they say they will.",
    author: "Homeowner", 
    location: "Edwards, CO",
  },
  {
    quote: "Clean wiring, clean install, and he walked us through everything before he left. Exactly what we needed.",
    author: "Builder",
    location: "Vail, CO",
  },
];
```

**Design:**
- Section bg: `bg-black/25 backdrop-blur-sm border-y border-white/5`
- Large quote marks (decorative, accent/10 color)
- Card-based layout: 3 columns on desktop, 1 column stacked on mobile
- Each card: `bg-black/40 border border-white/8 rounded-xl p-6`
- Quote text: `text-white/70 text-sm italic leading-relaxed`
- Author: `text-white font-semibold text-sm` + location in `text-white/40 text-xs`
- Section header: "What Clients Say" with accent eyebrow "Testimonials"

**Add a comment at the top of the component:** `// TODO: Replace placeholder testimonials with real client quotes`

**Import and add to Index.tsx** between `{/* How It Works */}` section and `<Testimonials />` (the featured projects).

---

## 4. ADD "MEET THE TEAM" SECTION (Index.tsx)

Add a brief team/about section between "Why Symphony" and "FAQ":

**Design:**
- No photo needed (keep it text-based for now)
- Left-aligned text block with accent eyebrow "The Team"
- Heading: "One Integrator. Every Project."
- Short paragraph: "Symphony is Matt Earley — one technician who oversees every project from first wire to final walkthrough. No subcontractors, no runaround. When you call, you talk to the person doing the work."
- Small CTA link: "Learn more about us →" linking to `/about`
- Right side (desktop): A stats grid with:
  - "Projects Completed" → "100+" (placeholder, Matt updates)
  - "Years in the Valley" → "10+"
  - "Response Time" → "Same Day"

---

## 5. BLOG FRAMEWORK (new route + page)

**Create the minimal blog infrastructure:**

### 5a. Create `src/data/blogPosts.ts`:
```typescript
export interface BlogPost {
  slug: string;
  title: string;
  excerpt: string;
  date: string; // ISO date string
  category: string;
  readTime: string;
  content: string; // Markdown or HTML content
}

export const blogPosts: BlogPost[] = [
  {
    slug: "smart-home-pre-wire-guide-vail-valley",
    title: "Smart Home Pre-Wire: What Every Vail Valley Builder Needs to Know",
    excerpt: "Pre-wiring during construction saves thousands and prevents headaches later. Here's what to plan for before drywall goes up.",
    date: "2026-04-16",
    category: "Pre-Wire",
    readTime: "5 min read",
    content: `
Pre-wiring is the single most cost-effective decision you can make during a new build or major renovation. Running cables before drywall costs a fraction of what it takes to retrofit later — and the results are cleaner, more reliable, and easier to maintain.

## What Gets Pre-Wired?

Every room that might eventually need technology should get at minimum:

- **Cat6 Ethernet** — for TVs, access points, security cameras, and smart home controllers
- **Speaker wire** — for in-ceiling or in-wall speakers (even if you're not installing them yet)
- **Coax** — still useful for certain antenna and satellite setups
- **HDMI conduit** — future-proof runs from equipment closets to display locations
- **Low-voltage power** — for motorized shades, keypads, and sensors

## The Most Common Mistake

Builders often ask electricians to handle low-voltage wiring. The problem: electricians think in terms of power, not data. You end up with speaker wire run in the same bundle as Romex, Cat5 instead of Cat6, and no home run topology.

A dedicated AV integrator plans the wiring around how the system will actually be used — not just where the outlets go.

## What It Costs

Pre-wire for a 3,000 sq ft home in the Vail Valley typically runs $3,000–$8,000 depending on complexity. That same work as a retrofit? Easily double, sometimes triple — plus drywall patches, paint touch-ups, and compromises on cable routing.

## When to Call

The ideal time is right after framing, before insulation. If you're a builder or GC in Eagle County planning a new project, reach out early. We'll walk the framing with you and plan every run.
    `,
  },
];
```

### 5b. Create `src/pages/Blog.tsx`:
- Page layout matching the rest of the site (dark bg, Header, Footer, PageBackground)
- List of blog posts as cards with title, excerpt, date, category badge, read time
- Link each card to `/blog/:slug`
- SEO component with title "Blog | Symphony Smart Homes" and description about smart home tips for Vail Valley

### 5c. Create `src/pages/BlogPost.tsx`:
- Single post view with full content rendering
- Back link to /blog
- Share buttons (simple: copy link)
- Related posts at bottom (just show the other posts)
- SEO component with the post title and excerpt as meta description
- Use `dangerouslySetInnerHTML` or a simple markdown-to-HTML approach for the content (keep it simple — content is trusted)

### 5d. Add routes in App.tsx:
```tsx
import Blog from "./pages/Blog";
import BlogPost from "./pages/BlogPost";
// Add inside <Routes>:
<Route path="/blog" element={<Blog />} />
<Route path="/blog/:slug" element={<BlogPost />} />
```

### 5e. Add "Blog" to nav:
- In `Header.tsx`, add to `navLinks` array: `{ label: "Blog", path: "/blog" }`
- In `Footer.tsx`, add Blog link to Quick Links

---

## 6. VISUAL POLISH TOUCHES

### 6a. Service cards (Index.tsx):
- Add a subtle gradient border on hover instead of just `border-accent/30`:
  ```
  hover:bg-gradient-to-br hover:from-accent/5 hover:to-transparent
  ```

### 6b. FAQ section:
- Add smooth height transition for FAQ answers (currently they snap open/closed)
- Wrap the answer `div` with a transition: use a CSS class with `max-height` transition or `grid-rows` animation

### 6c. Footer enhancement:
- Add a "Latest from the Blog" link in footer column 2 (under Quick Links), linking to `/blog`
- Add Google Business and social placeholder links at the bottom

### 6d. Global scroll-reveal:
- The `useScrollReveal` hook is already implemented — verify all sections on Index.tsx use `data-reveal` or `data-reveal-children` attributes (they mostly do already)

---

## 7. SEO QUICK WINS (in existing components)

### 7a. Add `alt` text to hero image:
In `Index.tsx` line ~96, change `alt=""` to `alt="Smart home automation control panel in a modern Vail Valley residence"`

### 7b. Verify structured data:
- `businessSchema.ts` already has LocalBusiness and FAQ schema — good
- Blog posts should get Article schema (add in BlogPost.tsx SEO component)

### 7c. Add Open Graph image:
- Ensure `/public/og-image.png` exists (if not, create a placeholder — 1200x630 dark bg with Symphony logo and tagline)

---

## COMMIT MESSAGE
```
feat: website polish — sticky nav, testimonials, team section, blog framework, visual enhancements
```

Push to main when done. Cloudflare Pages will auto-deploy.
