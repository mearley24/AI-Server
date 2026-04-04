# Auto-24: Symphony Portfolio Website — Auto-Generated from Project Data

## The Vision

785+ project photos sitting in Apple Notes. Completed projects with documented room configs, equipment lists, and before/after data. Bob auto-generates a public portfolio website that updates itself as new projects complete. Zero manual effort — finish a project, Bob builds the case study.

## Context Files to Read First
- tools/notes_sync.py (photo export by project)
- knowledge/projects/
- knowledge/products/*.md
- templates/tv_recommendations/generate.py (existing PDF generator pattern)

## Prompt

Build an auto-generated portfolio website for Symphony Smart Homes:

### 1. Project Data Pipeline (`tools/portfolio_builder.py`)

Aggregate project data from multiple sources:
- Photos from Apple Notes sync (`tools/notes_sync.py` — 785+ photos categorized by project)
- Room configs from `knowledge/projects/[project]/`
- Equipment lists from proposals
- Client testimonials (manually added to a `knowledge/testimonials/` directory)
- Project metadata: address (city only, not full), completion date, scope, value range

Output: `data/portfolio/projects.json` with structured project data

### 2. Static Site Generator (`tools/portfolio_generator.py`)

Generate a static website from the project data:

**Homepage:**
- Hero section: "Custom Smart Home Integration — Vail Valley, Colorado"
- Featured projects grid (3-4 best projects with hero photos)
- Services overview: Lighting, Audio/Video, Networking, Security, Automation, Shades
- "Powered by Symphony Smart Homes" branding

**Project Gallery (`/projects`):**
- Filterable grid by project type (full automation, AV only, retrofit, new construction)
- Each card: hero photo, project name (city + neighborhood only), scope badges, completion date
- Click → full case study page

**Case Study Pages (`/projects/[slug]`):**
- Photo gallery (carousel or grid)
- Scope summary: what was installed, which rooms, key features
- Equipment highlights: "This home features Control4 automation, Lutron lighting, Sonos distributed audio..."
- Technical stats: device count, speaker zones, camera count, network specs
- Before/after photos where available

**Services Pages (`/services/[type]`):**
- Lighting control, distributed audio, home theater, networking, surveillance, automation, motorized shades
- Each page: description, example installations, equipment brands used, typical pricing range

**Contact:**
- Simple contact form → sends email to info@symphonysh.com via Bob's email system
- Phone number, service area, business hours

### 3. Design

- Clean, modern, dark theme (matching Symphony branding)
- Mobile-first responsive
- Fast loading (static HTML, optimized images)
- SEO-friendly: meta tags, structured data, sitemap
- No JavaScript frameworks — vanilla HTML/CSS with minimal JS for gallery interactions

### 4. Photo Processing

- Auto-resize photos for web (max 1920px wide, compressed JPEG)
- Generate thumbnails (400px) for grid views
- Strip EXIF data (privacy — remove GPS coordinates)
- Auto-detect orientation and correct rotation
- Store processed photos in `data/portfolio/images/`

### 5. Auto-Update Pipeline

When a project is marked "Complete" in Linear:
- Bob pulls project data and photos
- Regenerates the case study page
- Rebuilds the static site
- Deploys to hosting (GitHub Pages or Netlify — free)
- Sends Matt an iMessage: "Portfolio updated with [Project Name]"

### 6. Hosting

- Generate to `apps/portfolio-site/` directory
- Deploy via GitHub Pages (free, custom domain support)
- Or deploy to Netlify with auto-deploy on git push
- Custom domain: symphonysmarthomes.com or portfolio.symphonysh.com

Use standard logging.
