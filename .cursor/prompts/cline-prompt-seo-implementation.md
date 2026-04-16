# Cline Prompt: SEO Implementation for symphonysh.com

**Repo:** `mearley24/symphonysh` (React + Vite + Tailwind + shadcn/ui, Cloudflare Pages)
**Goal:** Implement technical SEO foundations — sitemap, robots.txt, city landing pages, pre-rendering, schema markup. Commit and push when done.

---

## IMPORTANT RULES
- Test `npm run build` after changes to ensure zero errors
- Keep existing design aesthetic (dark bg, gold accent `#ca9f5c`)
- Do NOT break any existing pages or routes
- Match the visual style of existing service pages for any new pages

---

## 1. SITEMAP & ROBOTS.TXT

### Create `public/robots.txt`:
```
User-agent: *
Allow: /

Sitemap: https://symphonysh.com/sitemap.xml
```

### Create `public/sitemap.xml`:
Static sitemap covering all current routes. Priority and changefreq based on importance:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://symphonysh.com/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>https://symphonysh.com/services</loc><changefreq>monthly</changefreq><priority>0.9</priority></url>
  <url><loc>https://symphonysh.com/services/home-integration</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/audio-entertainment</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/smart-lighting</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/shades</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/networking</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/climate-control</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/security-systems</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/maintenance</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/services/prewire</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/projects</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/about</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://symphonysh.com/contact</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://symphonysh.com/scheduling</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>
  <url><loc>https://symphonysh.com/matterport</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>
  <url><loc>https://symphonysh.com/blog</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>
  <!-- City pages -->
  <url><loc>https://symphonysh.com/vail</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://symphonysh.com/beaver-creek</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://symphonysh.com/edwards</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://symphonysh.com/avon</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://symphonysh.com/eagle</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
</urlset>
```

---

## 2. CITY LANDING PAGES

Create 5 location-specific service pages. Each is a unique page — NOT a template with swapped city names.

### Data file: `src/data/cityPages.ts`

```typescript
export interface CityPage {
  slug: string;
  city: string;
  metaTitle: string;
  metaDescription: string;
  headline: string;
  subheadline: string;
  intro: string;
  localDetails: string;  // Paragraph about the specific area
  commonProjects: string[];  // Types of projects common in this area
  neighborhoods?: string[];
  driveTime?: string;  // From base of operations
}

export const cityPages: CityPage[] = [
  {
    slug: "vail",
    city: "Vail",
    metaTitle: "Smart Home Installation in Vail, CO",
    metaDescription: "Professional smart home integration in Vail, Colorado. Pre-wire, Control4, home theater, TV mounting, and whole-home audio. Local Vail Valley integrator.",
    headline: "Smart Home Integration in Vail",
    subheadline: "Local integrator serving Vail Village, Lionshead, West Vail, and East Vail",
    intro: "Vail homes range from slope-side condos to 10,000+ square foot mountain estates — and each has different technology needs. Whether you're wiring a new build from the ground up or retrofitting a rental property for smart access and climate control, we've done it here.",
    localDetails: "Vail's mix of primary residences and vacation homes creates unique smart home challenges. Remote access is critical — owners need to monitor security, adjust thermostats, and check on the property from anywhere. Altitude and mountain construction mean thicker walls, longer cable runs, and Wi-Fi dead zones that consumer mesh systems can't handle. We design systems that work reliably at 8,150 feet, in homes built into mountainsides, with stone and log construction that kills wireless signals.",
    commonProjects: ["Vacation home remote access systems", "Ski-in/ski-out condo retrofits", "New construction pre-wire", "Whole-home audio for entertaining", "Security cameras and smart locks for rental properties"],
    neighborhoods: ["Vail Village", "Lionshead", "West Vail", "East Vail", "Sandstone", "Potato Patch", "Golf Course"],
    driveTime: "Based in the valley — typically on-site within 30 minutes"
  },
  {
    slug: "beaver-creek",
    city: "Beaver Creek",
    metaTitle: "Smart Home Installation in Beaver Creek, CO",
    metaDescription: "Smart home integration for Beaver Creek residences and condos. Control4, home theater, pre-wire, and luxury AV systems. Local Eagle County integrator.",
    headline: "Smart Home Integration in Beaver Creek",
    subheadline: "Serving Bachelor Gulch, Arrowhead, and the Beaver Creek Village area",
    intro: "Beaver Creek properties are built to a high standard — and the technology should match. From custom homes in Bachelor Gulch to condos at the base, we install systems that deliver the experience high-end homeowners expect without the complexity.",
    localDetails: "Beaver Creek's gated community and resort-grade properties often require coordination with HOAs, property managers, and design teams. Many homes here have dedicated media rooms, multi-zone audio across indoor and outdoor spaces, and motorized shades managing mountain sun and privacy. Retrofit work in older Beaver Creek condos is common — we've run cable through crawl spaces and above drop ceilings in buildings where pre-wire wasn't part of the original plan.",
    commonProjects: ["Luxury whole-home automation", "Home theater and media rooms", "Multi-zone audio (indoor + outdoor)", "Motorized shade systems", "Retrofit wiring in older condos"],
    neighborhoods: ["Bachelor Gulch", "Arrowhead", "Beaver Creek Village", "Elkhorn", "Meadows"],
    driveTime: "15-minute drive from our base"
  },
  {
    slug: "edwards",
    city: "Edwards",
    metaTitle: "Smart Home Installation in Edwards, CO",
    metaDescription: "Smart home pre-wire, installation, and maintenance in Edwards, Colorado. TV mounting, networking, home automation. Serving Homestead and Riverwalk.",
    headline: "Smart Home Integration in Edwards",
    subheadline: "Serving Homestead, Riverwalk, Lake Creek, and surrounding Edwards neighborhoods",
    intro: "Edwards is where a lot of new construction in the valley happens — and that means pre-wire is the most common call we get here. New builds, major renovations, and the steady growth of the Riverwalk and Homestead areas keep us busy.",
    localDetails: "Edwards sits at the center of Eagle County's growth corridor. With new developments and a growing year-round population, there's a strong demand for networking infrastructure that can handle modern work-from-home setups, plus entertainment systems for families. We work closely with local builders and GCs here — many of the homes in Homestead and Lake Creek were pre-wired by us during construction.",
    commonProjects: ["New construction pre-wire", "Structured networking for home offices", "Family room TV and audio installations", "Builder partnerships", "Whole-home Wi-Fi systems"],
    neighborhoods: ["Homestead", "Riverwalk", "Lake Creek", "Berry Creek", "Edwards Village"],
    driveTime: "5-minute drive from our base"
  },
  {
    slug: "avon",
    city: "Avon",
    metaTitle: "Smart Home Installation in Avon, CO",
    metaDescription: "Professional smart home installation in Avon, Colorado. TV mounting, home automation, networking, and pre-wire services. Local Vail Valley integrator.",
    headline: "Smart Home Integration in Avon",
    subheadline: "Serving Avon, Wildridge, Mountain Star, and the I-70 corridor",
    intro: "Avon's growth as a year-round community means more homeowners want real smart home infrastructure — not just a few smart plugs and an Alexa. From the townhomes in Wildridge to custom builds in Mountain Star, we handle the wiring and programming.",
    localDetails: "Avon has a unique mix of affordable housing, mid-range townhomes, and high-end properties in neighborhoods like Mountain Star. We see a lot of TV mounting jobs and networking upgrades here — families want reliable Wi-Fi for streaming and remote work, plus clean entertainment setups in living rooms that are the center of the home. New developments often come to us for pre-wire during the framing stage.",
    commonProjects: ["TV mounting and soundbar installation", "Wi-Fi networking upgrades", "New construction pre-wire", "Smart thermostat and climate control", "Security camera systems"],
    neighborhoods: ["Wildridge", "Mountain Star", "Eaglebend", "Nottingham Park"],
    driveTime: "10-minute drive from our base"
  },
  {
    slug: "eagle",
    city: "Eagle",
    metaTitle: "Smart Home Installation in Eagle, CO",
    metaDescription: "Smart home installation and pre-wire services in Eagle, Colorado. TV mounting, networking, audio systems. Serving Eagle Ranch and Brush Creek.",
    headline: "Smart Home Integration in Eagle",
    subheadline: "Serving Eagle Ranch, Brush Creek, Haymeadow, and the Town of Eagle",
    intro: "Eagle is the fastest-growing part of the valley — and new neighborhoods mean new homes that need technology infrastructure from day one. We work with builders in Eagle Ranch, Haymeadow, and Brush Creek to get pre-wire right during construction.",
    localDetails: "Eagle's rapid growth and more affordable price point compared to Vail or Beaver Creek makes it a hotspot for families building their first custom home. Many homeowners here are tech-forward but budget-conscious — they want smart home capability without overbuilding. We help plan systems that can start simple (networking + a few zones of audio) and grow over time as needs and budgets expand. Eagle Ranch properties often share similar floor plans, which means we can dial in repeatable, efficient installations.",
    commonProjects: ["Budget-conscious smart home packages", "Pre-wire for new construction", "Scalable audio systems", "Networking for remote work", "TV and entertainment setups"],
    neighborhoods: ["Eagle Ranch", "Brush Creek", "Haymeadow", "Terrace", "Capitol"],
    driveTime: "20-minute drive from our base"
  },
];
```

### Create `src/pages/CityPage.tsx`

A single component that renders based on the slug from the route parameter:

Layout:
- Same dark bg + Header + Footer as all other pages
- Use PageBackground component (pick a generic hero image or use the existing bg-about.jpg)
- **Hero section:** City headline, subheadline, intro paragraph
- **Local details section:** The localDetails paragraph with "Why [City]?" heading
- **Common projects section:** List of commonProjects as a grid of cards
- **Neighborhoods section:** If neighborhoods exist, list them with MapPin icons
- **Services section:** Grid of 4-6 service cards linking to service pages (reuse from Index.tsx)
- **CTA section:** "Ready to talk about your [City] project?" with Schedule + Call buttons
- **SEO:** Full meta tags with city-specific title/description + LocalBusiness schema with city in service area

### Add routes in App.tsx:

```tsx
import CityPage from "./pages/CityPage";

// Inside <Routes>:
<Route path="/vail" element={<CityPage />} />
<Route path="/beaver-creek" element={<CityPage />} />
<Route path="/edwards" element={<CityPage />} />
<Route path="/avon" element={<CityPage />} />
<Route path="/eagle" element={<CityPage />} />
```

### Add to Footer.tsx:

Replace the static "Service Areas" list with links:
```tsx
{[
  { name: "Vail", path: "/vail" },
  { name: "Beaver Creek", path: "/beaver-creek" },
  { name: "Edwards", path: "/edwards" },
  { name: "Avon", path: "/avon" },
  { name: "Eagle", path: "/eagle" },
  { name: "Minturn", path: "/contact" }, // No dedicated page yet
].map((area) => (
  <li key={area.name}>
    <Link to={area.path} className="flex items-center gap-1.5 text-white/40 hover:text-white/70 text-sm transition-colors">
      <MapPin className="w-3 h-3 text-accent/60" />
      {area.name}
    </Link>
  </li>
))}
```

---

## 3. SCHEMA MARKUP ENHANCEMENTS

### Add Service schema to each service page

Create a helper `src/constants/serviceSchema.ts`:

```typescript
export function servicePageSchema(service: {
  name: string;
  description: string;
  url: string;
  areaServed?: string[];
}) {
  return {
    "@context": "https://schema.org",
    "@type": "Service",
    "name": service.name,
    "description": service.description,
    "url": `https://symphonysh.com${service.url}`,
    "provider": {
      "@type": "LocalBusiness",
      "name": "Symphony Smart Homes",
      "telephone": "+19705193013",
      "url": "https://symphonysh.com",
      "areaServed": (service.areaServed || ["Vail", "Beaver Creek", "Edwards", "Avon", "Eagle"]).map(city => ({
        "@type": "City",
        "name": `${city}, Colorado`
      }))
    },
    "areaServed": {
      "@type": "State",
      "name": "Colorado"
    }
  };
}
```

Add this schema to each service page's SEO component (AudioEntertainment, ClimateControl, HomeIntegration, Maintenance, Networking, SecuritySystems, Shades, SmartLighting, PreWire).

### Add BreadcrumbList schema to all pages

The SEO component already supports breadcrumbs — ensure every page passes them:
- Services pages: `[{Home, /}, {Services, /services}, {Service Name, /services/slug}]`
- Projects: `[{Home, /}, {Projects, /projects}]`
- City pages: `[{Home, /}, {City Name, /city-slug}]`
- Blog: `[{Home, /}, {Blog, /blog}]` and `[{Home, /}, {Blog, /blog}, {Post Title, /blog/slug}]`

---

## 4. OPEN GRAPH IMAGE

Check if `public/og-image.png` exists. If not, create a simple OG image:
- 1200x630px
- Dark background (#000000)
- Symphony logo centered (reference: `/public/lovable-uploads/symphony-logo-transparent.webp`)
- Tagline below: "Smart Home Integration | Vail Valley"
- Gold accent line underneath

If creating programmatically isn't feasible, create a placeholder HTML file that can be screenshotted, or just ensure the meta tag points to an existing image.

---

## 5. CLOUDFLARE PAGES HEADERS

Create `public/_headers` for Cloudflare Pages:

```
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/*.html
  Cache-Control: public, max-age=0, must-revalidate
```

---

## 6. INTERNAL LINKING

Add cross-links between related pages:
- Each service page should link to 1-2 related services at the bottom (e.g., Smart Lighting links to Shades and Home Integration)
- City pages link to relevant service pages
- Blog posts link to relevant service pages (when blog is implemented)

For now, focus on service page cross-links. Add a "Related Services" section at the bottom of each service page (before the CTA), showing 2-3 cards for related services.

---

## COMMIT MESSAGE
```
feat: SEO foundations — sitemap, robots.txt, city pages, schema markup, headers
```

Push to main when done. Cloudflare Pages will auto-deploy.
