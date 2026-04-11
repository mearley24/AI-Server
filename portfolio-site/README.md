# Symphony Smart Homes — Portfolio Site Generator

A self-contained Python tool that generates a beautiful, fast static HTML/CSS portfolio website from a simple JSON data file.

**No build pipeline. No Node. No React.** Just Python + Jinja2.

---

## Quick Start

```bash
# 1. Install the one dependency
pip install -r requirements.txt

# 2. Generate the site from sample data
python generate_portfolio.py

# 3. Preview locally
cd output && python -m http.server 8080
# Open http://localhost:8080
```

---

## File Structure

```
portfolio-site/
├── generate_portfolio.py      # ← The generator (run this)
├── requirements.txt           # Jinja2 only
├── portfolio_schema.json      # JSON schema for projects.json
├── sample_projects.json       # 5 example Symphony projects
│
├── templates/
│   ├── base.html              # Shared layout (header, nav, footer)
│   ├── index.html             # Portfolio grid with category filters
│   └── project.html           # Individual project detail page
│
├── static/
│   ├── style.css              # Complete stylesheet (dark/light modes)
│   └── favicon.svg            # SVG favicon
│
├── photos/                    # Drop project photos here (see below)
│   └── {project-id}/
│       ├── living-room.jpg
│       └── theater.jpg
│
└── output/                    # ← Generated site (deploy this folder)
    ├── index.html
    ├── {project-id}.html
    ├── static/
    └── photos/
```

---

## Adding Your Projects

### 1. Edit `projects.json` (or copy `sample_projects.json`)

Each project in the `projects` array takes:

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | ✓ | URL-safe slug, e.g. `"topletz-84-aspen"` |
| `name` | string | ✓ | Display name, e.g. `"Topletz Residence"` |
| `location` | string | ✓ | City/state, e.g. `"Beaver Creek, CO"` |
| `categories` | array | ✓ | One or more from: `whole-home`, `theater`, `lighting`, `audio`, `networking`, `outdoor`, `security`, `commercial` |
| `scope` | string | ✓ | One-line description shown on the card |
| `completion_date` | string | | `"YYYY-MM"` format, e.g. `"2026-05"` |
| `description` | string | | Longer narrative (HTML allowed) for the detail page |
| `photos` | array | | Filenames of photos in `photos/{id}/` |
| `featured_photo` | string | | Filename used as the card thumbnail |
| `systems_installed` | array | | Brand/model list shown in the sidebar |
| `value_range` | string | | `standard`, `premium`, `luxury`, or `ultra` |
| `square_footage` | integer | | Displayed in project specs |
| `testimonial` | object\|null | | `{ "quote": "...", "author": "...", "title": "..." }` |
| `featured` | boolean | | `true` pins the project to the top and gives it a wide card |

**Full schema:** see `portfolio_schema.json`.

### 2. Add photos

Place photos into `photos/{project-id}/` next to `projects.json`:

```
photos/
└── topletz-84-aspen-meadow/
    ├── living-room.jpg   ← referenced in "featured_photo"
    ├── theater.jpg
    └── rack.jpg
```

Photos are automatically copied to `output/photos/` during generation. If no photos are provided, the generator shows a tasteful architectural placeholder SVG.

### 3. Run the generator

```bash
python generate_portfolio.py --data projects.json --output output/
```

Available flags:

| Flag | Default | Description |
|---|---|---|
| `--data PATH` | `sample_projects.json` | Input JSON file |
| `--output PATH` | `output/` | Where to write the site |
| `--templates PATH` | `templates/` | Jinja2 template directory |
| `--static PATH` | `static/` | CSS/favicon source directory |
| `--photos PATH` | `photos/` | Photos source directory |
| `--clean` | off | Wipe output dir before generating |

---

## Deploying

The `output/` folder is a complete, self-contained static website. Deploy it anywhere:

### Netlify (drag & drop)
1. Go to [app.netlify.com](https://app.netlify.com)
2. Drag the `output/` folder onto the deploy area
3. Done — you get a live URL instantly

### Amazon S3 + CloudFront
```bash
aws s3 sync output/ s3://your-bucket-name/ --delete
```

### GitHub Pages
```bash
cp -r output/ docs/
git add docs/ && git commit -m "Update portfolio"
git push
# Set GitHub Pages source to /docs in repo Settings
```

### Vercel
```bash
npm i -g vercel
cd output && vercel
```

### Any web host
Upload the contents of `output/` via FTP/SFTP to your `public_html` folder.

---

## Customizing the Design

### Colors & branding
All design tokens are at the top of `static/style.css` under `:root` and `[data-theme="dark"]`/`[data-theme="light"]`. The gold accent color (`--color-gold`) and background shades are the two most impactful variables to change.

### Logo
The SVG logo is inlined in `templates/base.html` inside `.site-logo`. Replace the `<svg>` markup with your own.

### Fonts
Loaded from Fontshare CDN in `templates/base.html`. Currently: **Cabinet Grotesk** (headings) + **Satoshi** (body). Change the CDN URL and the `--font-display`/`--font-body` CSS variables to swap fonts.

### Site meta (phone, email, service areas)
Set these in the top-level `"site"` object in your `projects.json`:

```json
{
  "site": {
    "company_name": "Symphony Smart Homes",
    "tagline": "Vail Valley Smart Home Integrator",
    "phone": "(970) 519-3013",
    "email": "info@symphonysh.com",
    "website": "https://symphonysh.com",
    "service_areas": ["Vail", "Beaver Creek", "Edwards", "Avon", "Eagle"]
  },
  "projects": [...]
}
```

### Adding new category filters
1. Add the category slug to `CATEGORIES` in `generate_portfolio.py`
2. Use the new slug in your project's `categories` array
3. Re-run the generator

---

## How It Works

1. `generate_portfolio.py` reads `projects.json`
2. Sorts projects (featured first, then newest-first by `completion_date`)
3. Determines which categories are in use and builds the filter bar
4. Renders `templates/index.html` → `output/index.html`
5. Renders `templates/project.html` once per project → `output/{id}.html`
6. Copies `static/` → `output/static/`
7. Copies `photos/` → `output/photos/`

Filtering is pure vanilla JS — no frameworks, no build step. Clicking a filter button shows/hides cards using `hidden` attribute and `data-categories`.

---

## Integration with AI-Server

When dropped into the AI-Server repo, the generator can be invoked via a simple API endpoint:

```python
# ai_server/routes/portfolio.py (example)
import subprocess, os

def regenerate_portfolio(data: dict):
    # Write updated projects.json
    with open("portfolio-site/projects.json", "w") as f:
        json.dump(data, f)
    # Run generator
    result = subprocess.run(
        ["python", "portfolio-site/generate_portfolio.py",
         "--data", "portfolio-site/projects.json",
         "--output", "portfolio-site/output/",
         "--clean"],
        capture_output=True, text=True
    )
    return result.returncode == 0
```

Then serve `portfolio-site/output/` as static files from the AI-Server.

---

## Requirements

- Python 3.8+
- Jinja2 3.1+ (`pip install jinja2`)
- No other dependencies

---

## License

MIT — Symphony Smart Homes internal tooling.
