#!/usr/bin/env python3
"""
Symphony Smart Homes — Static Portfolio Site Generator
=======================================================
Reads a projects.json file and generates a complete static HTML/CSS
portfolio website using Jinja2 templates.

Usage:
    python generate_portfolio.py [options]

Options:
    --data PATH       Path to projects JSON file  (default: sample_projects.json)
    --output PATH     Output directory             (default: output/)
    --templates PATH  Template directory           (default: templates/)
    --static PATH     Static assets directory      (default: static/)
    --photos PATH     Photos source directory      (default: photos/)
    --clean           Delete and recreate output directory before generating
    --help            Show this message and exit

Example:
    python generate_portfolio.py --data projects.json --output dist/
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    print("ERROR: Jinja2 is not installed. Run: pip install jinja2")
    sys.exit(1)


# ─── CATEGORY DEFINITIONS ────────────────────────────────────────────────────

CATEGORIES = [
    {"id": "whole-home",  "label": "Whole-Home"},
    {"id": "theater",     "label": "Home Theater"},
    {"id": "lighting",    "label": "Lighting"},
    {"id": "audio",       "label": "Audio"},
    {"id": "networking",  "label": "Networking"},
    {"id": "outdoor",     "label": "Outdoor"},
    {"id": "security",    "label": "Security"},
    {"id": "commercial",  "label": "Commercial"},
]

CATEGORY_LABELS = {c["id"]: c["label"] for c in CATEGORIES}


# ─── JINJA2 FILTERS ──────────────────────────────────────────────────────────

def format_date(value: str) -> str:
    """Convert '2026-05' to 'May 2026', or return raw value on failure."""
    if not value:
        return ""
    try:
        dt = datetime.strptime(str(value), "%Y-%m")
        return dt.strftime("%B %Y")
    except ValueError:
        return str(value)


def now_filter(value, fmt_type, fmt_str):
    """Minimal {% now %} implementation — returns current UTC time formatted."""
    return datetime.utcnow().strftime(fmt_str)


# ─── DATA LOADING & VALIDATION ───────────────────────────────────────────────

def load_projects(data_path: Path) -> dict:
    """Load and lightly validate the projects JSON file."""
    if not data_path.exists():
        print(f"ERROR: Data file not found: {data_path}")
        sys.exit(1)

    with data_path.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"ERROR: Invalid JSON in {data_path}: {e}")
            sys.exit(1)

    if "projects" not in data:
        print(f"ERROR: {data_path} must have a top-level 'projects' array.")
        sys.exit(1)

    # Coerce each project's photos/systems_installed to lists
    for project in data["projects"]:
        project.setdefault("photos", [])
        project.setdefault("systems_installed", [])
        project.setdefault("categories", [])
        project.setdefault("featured", False)
        project.setdefault("testimonial", None)
        project.setdefault("value_range", None)
        project.setdefault("description", "")
        project.setdefault("square_footage", None)
        project.setdefault("featured_photo", None)
        project.setdefault("photo_credits", None)

        # Validate id is URL-safe
        pid = project.get("id", "")
        if not pid:
            print(f"WARNING: A project is missing an 'id' field — skipping.")
            continue
        if not re.match(r"^[a-z0-9-]+$", pid):
            print(f"WARNING: Project id '{pid}' contains invalid characters. Use lowercase letters, digits, and hyphens only.")

    # Deduplicate: filter projects with missing ids
    data["projects"] = [p for p in data["projects"] if p.get("id")]

    # Sort: featured first, then by completion_date descending
    def sort_key(p):
        featured = 0 if p.get("featured") else 1
        date_str = p.get("completion_date", "0000-00")
        return (featured, [-ord(c) for c in date_str])

    data["projects"].sort(key=lambda p: (
        0 if p.get("featured") else 1,
        p.get("completion_date", "0000-00")
    ), reverse=False)
    # Actually sort featured first, then desc date
    data["projects"] = sorted(
        data["projects"],
        key=lambda p: (
            not p.get("featured", False),
            p.get("completion_date", "0000-00")
        ),
        reverse=False
    )

    return data


# ─── JINJA2 ENV SETUP ────────────────────────────────────────────────────────

def build_jinja_env(templates_dir: Path) -> Environment:
    """Create and configure the Jinja2 environment."""
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Register filters
    env.filters["format_date"] = format_date

    # Register current_year global (used in base.html footer)
    env.globals["current_year"] = datetime.now().year

    return env


# ─── SITE GENERATION ─────────────────────────────────────────────────────────

def generate_site(
    data_path: Path,
    output_dir: Path,
    templates_dir: Path,
    static_dir: Path,
    photos_dir: Path,
    clean: bool,
) -> None:
    print(f"\n{'='*56}")
    print(f"  Symphony Smart Homes — Portfolio Site Generator")
    print(f"{'='*56}")
    print(f"  Data:      {data_path}")
    print(f"  Templates: {templates_dir}")
    print(f"  Static:    {static_dir}")
    print(f"  Photos:    {photos_dir}")
    print(f"  Output:    {output_dir}")
    print(f"{'='*56}\n")

    # ── Clean or create output directory
    if clean and output_dir.exists():
        print(f"  [clean] Removing existing output directory...")
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Load data
    data = load_projects(data_path)
    projects = data["projects"]
    site_meta = data.get("site", {})

    print(f"  Loaded {len(projects)} project(s) from {data_path.name}")

    # ── Determine which categories actually appear in the data
    used_cats = set()
    for p in projects:
        used_cats.update(p.get("categories", []))
    active_categories = [c for c in CATEGORIES if c["id"] in used_cats]

    # ── Set up Jinja2
    env = build_jinja_env(templates_dir)

    # Common template context
    base_ctx = {
        "site": site_meta,
        "categories": active_categories,
        "category_labels": CATEGORY_LABELS,
    }

    # ── Render index.html
    print("  Generating index.html ...", end="")
    index_tpl = env.get_template("index.html")
    index_html = index_tpl.render(
        **base_ctx,
        projects=projects,
        static_prefix="static/",
        root_prefix="",
        active_page="portfolio",
        meta_description=(
            f"{site_meta.get('company_name', 'Symphony Smart Homes')} — "
            f"Portfolio of smart home, theater, lighting, and AV projects across "
            f"{', '.join(site_meta.get('service_areas', ['Colorado']))}."
        ),
    )
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")
    print(" ✓")

    # ── Render project detail pages
    project_tpl = env.get_template("project.html")
    for project in projects:
        pid = project["id"]
        out_path = output_dir / f"{pid}.html"
        print(f"  Generating {pid}.html ...", end="")
        project_html = project_tpl.render(
            **base_ctx,
            project=project,
            static_prefix="static/",
            root_prefix="",
            active_page="portfolio",
            meta_description=(
                f"{project.get('name', '')} in {project.get('location', '')}. "
                f"{project.get('scope', '')}"
            ),
        )
        out_path.write_text(project_html, encoding="utf-8")
        print(" ✓")

    # ── Copy static assets (CSS, favicon, etc.)
    static_out = output_dir / "static"
    if static_dir.exists():
        print(f"  Copying static assets ...", end="")
        if static_out.exists():
            shutil.rmtree(static_out)
        shutil.copytree(str(static_dir), str(static_out))
        print(" ✓")
    else:
        print(f"  WARNING: Static directory not found at {static_dir} — skipping.")

    # ── Copy photos
    photos_out = output_dir / "photos"
    if photos_dir.exists():
        print(f"  Copying photos ...", end="")
        if photos_out.exists():
            shutil.rmtree(photos_out)
        shutil.copytree(str(photos_dir), str(photos_out))
        # Count photos
        photo_count = sum(1 for _ in photos_out.rglob("*") if _.is_file())
        print(f" ✓  ({photo_count} file(s))")
    else:
        print(f"  [info] No photos directory found at {photos_dir} — placeholder graphics will be shown.")
        # Still create the directory so the output is valid
        photos_out.mkdir(exist_ok=True)

    # ── Summary
    total_pages = 1 + len(projects)
    print(f"\n{'='*56}")
    print(f"  ✓ Built {total_pages} page(s) → {output_dir}/")
    print(f"    • index.html")
    for p in projects:
        print(f"    • {p['id']}.html")
    print(f"\n  To preview locally:")
    print(f"    cd {output_dir} && python -m http.server 8080")
    print(f"    then open http://localhost:8080")
    print(f"\n  To deploy: upload the entire '{output_dir}' folder to")
    print(f"    any static host (S3, Netlify, Vercel, GitHub Pages, etc.)")
    print(f"{'='*56}\n")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Symphony Smart Homes — Static Portfolio Site Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=Path("sample_projects.json"),
        metavar="PATH",
        help="Path to projects JSON file (default: sample_projects.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        metavar="PATH",
        help="Output directory (default: output/)",
    )
    parser.add_argument(
        "--templates",
        type=Path,
        default=Path("templates"),
        metavar="PATH",
        help="Jinja2 templates directory (default: templates/)",
    )
    parser.add_argument(
        "--static",
        type=Path,
        default=Path("static"),
        metavar="PATH",
        help="Static assets directory (default: static/)",
    )
    parser.add_argument(
        "--photos",
        type=Path,
        default=Path("photos"),
        metavar="PATH",
        help="Photos source directory (default: photos/)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        default=False,
        help="Delete output directory before generating",
    )

    args = parser.parse_args()

    # Resolve paths relative to the script's location
    script_dir = Path(__file__).parent

    def resolve(p: Path) -> Path:
        if p.is_absolute():
            return p
        return (script_dir / p).resolve()

    generate_site(
        data_path=resolve(args.data),
        output_dir=resolve(args.output),
        templates_dir=resolve(args.templates),
        static_dir=resolve(args.static),
        photos_dir=resolve(args.photos),
        clean=args.clean,
    )


if __name__ == "__main__":
    main()
