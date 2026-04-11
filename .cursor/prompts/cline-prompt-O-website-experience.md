# Cline Prompt O — Website Experience Overhaul

## Context
symphonysh.com is a React+Vite+shadcn/ui site at `~/symphonysh` (repo: `mearley24/symphonysh`). It deploys via Cloudflare Pages on push to main. The site currently has two problems:

1. **Fake testimonials** — `src/components/Testimonials.tsx` has 3 placeholder quotes with `// TODO` comments visible in source. These need to go immediately.
2. **Disconnected portfolio** — `/projects` is a flat list of photo gallery categories. There's no story, no context, no reason for a visitor to care. The photos are real and good — they just need a wrapper that makes them feel like completed projects, not a photo dump.

The goal: make the website feel like an **experience** — a visitor should flow naturally from seeing the work → understanding what was done → wanting to reach out. Not a test. Not a brochure. An experience.

## Real projects to use (these are REAL jobs — no made-up data)

### Eagle-Vail Theater
- **Location:** Eagle-Vail, CO
- **Category:** Home Theater
- **Photos:** Already in `/lovable-uploads/home theater/` — IMG_0920 through IMG_0982
- **Scope:** Dedicated home theater build in existing basement space
- **Equipment:** (leave equipment list empty for now — Matt will fill in)
- **Testimonial:** None yet — leave the slot empty/hidden

### Beaver Creek Condo
- **Location:** Beaver Creek, CO
- **Category:** TV Mounting, Fireplace
- **Photos:** Already in `/lovable-uploads/mounted tvs/BC Condo FP/`
- **Scope:** Fireplace TV mount with concealed wiring in ski condo
- **Testimonial:** None yet

### Cordillera Media Room
- **Location:** Cordillera, CO
- **Category:** Home Theater
- **Photos:** Already in `/lovable-uploads/home theater/IMG_0958.JPG`
- **Scope:** Media room integration
- **Testimonial:** None yet

### West Vail
- **Location:** West Vail, CO
- **Category:** TV Mounting
- **Photos:** Already in `/lovable-uploads/mounted tvs/West Vail BB/`
- **Scope:** TV mounting and audio setup
- **Testimonial:** None yet

## Task 1: Kill the fake testimonials

Edit `src/components/Testimonials.tsx`:
- Remove ALL placeholder testimonial data (the 3 fake quotes with Sarah K., James T., Maria L.)
- Replace with a **"Featured Project Spotlight"** section instead — show 1-2 real project photos from the galleries above with a link to the full project page
- If zero approved testimonials exist, the testimonial cards section should not render at all — no empty states, no "coming soon"
- Keep the component file and its import in Index.tsx — just change what it renders

## Task 2: Fix SocialProof.tsx

Edit `src/components/SocialProof.tsx`:
- Remove the `// TODO` comments about placeholder numbers
- Change "150+ Projects Completed" to "Eagle County" with sublabel "Based & operating locally"
- Change "10+ Years Experience" to "Full-Service" with sublabel "Pre-wire through programming"  
- Keep "Denver Metro & Mountain Communities" → change to "Vail Valley" / "& Eagle County"
- Keep "Control4 Authorized Dealer"
- These are all true statements — no inflated numbers, no fake stats

## Task 3: Restructure Projects page into case study hub

Replace the current `src/pages/Projects.tsx` with a new design:

### New Projects page structure:
1. **Hero** — keep existing hero text: "Real projects. Real homes. Vail Valley."
2. **Project cards** — each card is a real project (not a category), showing:
   - Hero photo from the gallery
   - Project name (location-based: "Eagle-Vail Theater", "Beaver Creek Condo", etc.)
   - Location badge
   - One-line scope description
   - Category tags (Home Theater, TV Mounting, Wiring, etc.)
   - Arrow link to the individual project page
3. **Category filter bar** — keep the existing filter concept (Home Theater, Mounted TVs, Wiring) but as filter pills above the project cards, not as the cards themselves
4. **CTA** — keep the existing "Ready to start your project?" CTA at bottom

### Individual project pages
Create a new component `src/pages/ProjectDetail.tsx` that renders each project:

```
/projects/:slug → ProjectDetail
```

Layout:
- **Back to Projects** breadcrumb
- **Project title** (large) + location badge + category tags
- **Hero photo** (full-width, the best shot from the gallery)
- **Photo gallery** — reuse the existing `PhotoGallery.tsx` component with photos from the project
- **Project Details sidebar** (or section below on mobile):
  - Location
  - Scope description (2-3 sentences about what was done)
  - Systems Installed list (initially empty — Matt fills in later, hide section if empty)
  - Testimonial card (hidden if none exists — will be populated via the review collection flow later)
- **CTA** — "Like what you see?" → Schedule a Walkthrough

### Data structure
Create `src/data/projects.ts`:

```typescript
export interface Project {
  slug: string;
  name: string;
  location: string;
  categories: string[];
  scope: string;
  description: string;
  photos: string[];
  heroPhoto: string;
  systemsInstalled?: string[];
  testimonial?: {
    quote: string;
    author: string;
    title: string;
  } | null;
}

export const projects: Project[] = [
  {
    slug: "eagle-vail-theater",
    name: "Eagle-Vail Theater",
    location: "Eagle-Vail, CO",
    categories: ["theater"],
    scope: "Dedicated home theater build in existing basement space.",
    description: "A dedicated theater room carved from an existing basement — acoustic treatment, projection, surround sound, and Control4 integration for a one-button cinema experience.",
    heroPhoto: "/lovable-uploads/home theater/IMG_0979.JPG",
    photos: [
      "/lovable-uploads/home theater/IMG_0920.JPG",
      "/lovable-uploads/home theater/IMG_0921.JPG",
      "/lovable-uploads/home theater/IMG_0925.JPG",
      "/lovable-uploads/home theater/IMG_0926.JPG",
      "/lovable-uploads/home theater/IMG_0979.JPG",
      "/lovable-uploads/home theater/IMG_0981.JPG",
      "/lovable-uploads/home theater/IMG_0982.JPG"
    ],
    systemsInstalled: [],
    testimonial: null,
  },
  {
    slug: "beaver-creek-condo",
    name: "Beaver Creek Condo",
    location: "Beaver Creek, CO",
    categories: ["tv-mounting"],
    scope: "Fireplace TV mount with concealed wiring in ski condo.",
    description: "A clean fireplace TV installation in a Beaver Creek ski condo — all wiring concealed behind the wall, no visible cables, no exposed conduit.",
    heroPhoto: "/lovable-uploads/mounted tvs/BC Condo FP/IMG_0677.JPG",
    photos: [
      "/lovable-uploads/mounted tvs/BC Condo FP/70551934893__F08E6641-B90D-4FE9-96CB-B6043C9EFBB7.jpg",
      "/lovable-uploads/mounted tvs/BC Condo FP/70682259838__CA09AB38-91D5-434E-9D12-D8D3BEC77650.JPG",
      "/lovable-uploads/mounted tvs/BC Condo FP/70682261617__B029C99B-C48B-4344-B91B-06B9B4921F7C.JPG",
      "/lovable-uploads/mounted tvs/BC Condo FP/IMG_0610.JPG",
      "/lovable-uploads/mounted tvs/BC Condo FP/IMG_0677.JPG",
      "/lovable-uploads/mounted tvs/BC Condo FP/IMG_0678.JPG",
      "/lovable-uploads/mounted tvs/BC Condo FP/IMG_0679.JPG"
    ],
    systemsInstalled: [],
    testimonial: null,
  },
  {
    slug: "cordillera-media-room",
    name: "Cordillera Media Room",
    location: "Cordillera, CO",
    categories: ["theater"],
    scope: "Media room integration in mountain residence.",
    description: "A media room built for everyday use — clean sight lines, architectural speakers, and automation that disappears into the room.",
    heroPhoto: "/lovable-uploads/home theater/IMG_0958.JPG",
    photos: [
      "/lovable-uploads/home theater/IMG_0958.JPG"
    ],
    systemsInstalled: [],
    testimonial: null,
  },
  {
    slug: "west-vail-install",
    name: "West Vail Residence",
    location: "West Vail, CO",
    categories: ["tv-mounting"],
    scope: "TV mounting and structured wiring.",
    description: "Multiple TV installations with clean cable management and structured wiring behind the walls.",
    heroPhoto: "/lovable-uploads/mounted tvs/West Vail BB/IMG_0134.JPG",
    photos: [
      "/lovable-uploads/mounted tvs/West Vail BB/IMG_0134.JPG",
      "/lovable-uploads/mounted tvs/West Vail BB/IMG_0135.JPG"
    ],
    systemsInstalled: [],
    testimonial: null,
  },
];

export const projectCategories = [
  { slug: "all", label: "All Projects" },
  { slug: "theater", label: "Home Theater" },
  { slug: "tv-mounting", label: "TV Mounting" },
  { slug: "wiring", label: "Wiring" },
  { slug: "whole-home", label: "Whole-Home" },
  { slug: "outdoor", label: "Outdoor" },
];
```

## Task 4: Add routes

Edit `src/App.tsx`:
- Add: `import ProjectDetail from "./pages/ProjectDetail";`
- Add route: `<Route path="/projects/:slug" element={<ProjectDetail />} />`
- Keep existing `/projects` route pointing to the updated Projects page
- Keep existing `/photos/*` routes — they still work as deep-link galleries
- Keep the redirect: `/portfolio` → `/projects`

## Task 5: Update homepage Testimonials → Featured Work

Since we killed the fake testimonials in Task 1, the `<Testimonials />` component on the homepage should now render a **"Featured Work"** section instead:

- Show 2-3 project cards from `src/data/projects.ts` (import and use the first few)
- Each card: hero photo, project name, location, scope one-liner, link arrow
- Section header: "Recent Work" or "Featured Projects" (not "What Clients Say")
- This replaces the old testimonials position between "Our Process" and "Why Us"
- When real testimonials come in later (via the collection flow), we can add a separate testimonials section back — but only with real quotes

## Task 6: Smooth transitions

Add page-level transitions using CSS:
- Fade-in on route change (0.3s ease)
- Stagger project card animations on the Projects page (each card fades in 100ms after the previous)
- Photo gallery images should lazy-load with a subtle fade-in as they appear in viewport
- The filter bar on Projects should animate card show/hide (not just display:none snap)

Do NOT add any animation library — use CSS transitions and `IntersectionObserver` only.

## Task 7: Navigation update

Edit `src/components/Header.tsx`:
- The nav should have: **Home** | **Services** | **Our Work** | **About** | **Contact**
- "Our Work" links to `/projects` (currently it might say "Projects" — rename to "Our Work" for warmer tone)
- On the Projects page and ProjectDetail pages, "Our Work" should have an active state (underline or accent color)

## Design rules

- Keep the exact same dark aesthetic, color palette, and typography
- Gold accent color stays (`accent` in tailwind config)
- Glass/blur effects stay
- No new fonts, no new colors, no design system changes
- Project cards should match the existing service card style (rounded-xl, border-white/8, bg-black/40, backdrop-blur)
- Everything mobile-responsive down to 375px
- Hero photos on project cards: `aspect-[16/9]` with gradient overlay for text readability
- Category filter pills: same style as the existing FAQ accordion buttons

## What NOT to do

- Do NOT create fake testimonials or placeholder quotes
- Do NOT add fake stats or numbers
- Do NOT change the hero section on the homepage
- Do NOT remove any existing photo gallery pages or routes — they should still work as direct links
- Do NOT add any new npm dependencies
- Do NOT touch anything in the AI-Server repo — this is symphonysh repo only

## Build & Deploy

```zsh
cd ~/symphonysh
npm run build
```

Fix any TypeScript errors. Then:

```zsh
git add -A
git commit -m "Website experience overhaul: kill fake testimonials, project case studies, featured work section"
git push origin main
```

Cloudflare Pages auto-deploys on push.

## Verification

After build succeeds, verify:
1. Homepage loads — no fake testimonials visible, "Featured Work" section shows real project photos
2. `/projects` shows project cards with filter pills — clicking a card goes to `/projects/eagle-vail-theater`
3. `/projects/eagle-vail-theater` shows photo gallery, scope description, breadcrumb back to projects
4. Old gallery routes still work: `/photos/home-theater` etc.
5. Social proof section has no TODO comments in source
6. Mobile layout works on 375px width
7. No console errors
