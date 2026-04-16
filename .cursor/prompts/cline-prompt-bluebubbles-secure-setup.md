# Cline Autorun — BlueBubbles Secure Setup Guide PDF

> **Cline:** read this file top-to-bottom. Operate in **Plan → Act** mode: restate the goal, post a short plan, then execute without further prompting unless a Guardrail (§9) forces a stop. After each tool use, summarize in ≤3 bullets. When done, produce the Final Report in the format in §10.
>
> `AUTO_APPROVE = true` — proceed through all steps unless a guardrail triggers.

---

## 1. Role & Operating Mode

You are Cline, an autonomous coding agent running inside VS Code with filesystem + terminal access.

- Think first, write second. Always produce a numbered plan before touching files.
- Never invent files, packages, or APIs — verify with `read_file`, `search_files`, `list_files`, or a web fetch first.
- Prefer editing existing files over creating new ones.
- Use conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`.
- If blocked on the same sub-problem for >2 tool calls, stop and surface the blocker.

## 2. Objective

Generate a polished, print-ready PDF titled **"BlueBubbles — Secure Local-First Setup Guide"** at `/home/user/workspace/BlueBubbles_Secure_Setup_Guide.pdf`. The guide walks a self-hoster through installing BlueBubbles on macOS with Tailscale VPN (no port-forwarding), documents the SIP / Private API trade-off, covers Docker-OSX self-hosting, and provides Android + Windows client checklists with TLS verification. The PDF must have clickable hyperlinks, numbered footnote citations, and the Perplexity Nexus palette.

## 3. Environment

- **Working dir:** `/home/user/workspace`
- **Python:** 3.11+ (use the system interpreter unless a venv exists)
- **Required packages (install if missing):** `reportlab`, `pypdf`. Check with `python -c "import reportlab, pypdf"` before installing.
- **CLI tools available:** `pdftotext`, `pdfinfo`, `pdftoppm`, `qpdf`, `curl`.
- **Network:** allowed for Google Fonts TTF downloads only.

## 4. Design Constraints

- **Library:** ReportLab Platypus (`SimpleDocTemplate`). Do **not** switch to WeasyPrint, LaTeX, or pdf-lib.
- **Fonts (download at runtime into `/tmp/fonts_bb/`, register with `pdfmetrics.registerFont`):**
  - Headings → DM Sans Bold
  - Body → Inter
  - Code → JetBrains Mono (Regular + Bold)
  - Fallback on download failure → Helvetica; log a warning, don't abort.
- **Palette (Nexus light):**
  - bg `#F7F6F2`, surface `#F9F8F5`, surface_alt `#FBFBF9`
  - border `#D4D1CA`, text `#28251D`, muted `#7A7974`, faint `#BAB9B4`
  - primary `#01696F`, warning `#964219`, error `#A12C7B`, success `#437A22`
- **PDF metadata:**
  - Title = `BlueBubbles — Secure Local-First Setup Guide`
  - Author = `Perplexity Computer`
- **Typography:** body 10pt / 14pt leading; H1 20pt; H2 14pt primary color; H3 11pt.
- **Page:** US Letter, 0.9" L/R margins, 0.8" T/B margins.

### Prohibited

- Unicode super/subscript characters (`²`, `₃`, `⁰`, etc.) — use `<super>` / `<sub>` XML tags.
- Unicode checkbox glyphs (`☐`, `☑`) — Inter lacks these. Use a bracketed mark like `[ ]` in `DMSans-Bold` with the primary color.
- Stock imagery, decorative icons, clipart.
- More than one accent color.

## 5. Required Section Order

1. Cover (title, subtitle, 3-column scope/audience/outcome card, Contents list)
2. Threat model & design goals
3. Prerequisites & macOS permissions (table with Permission / Required for / Where to grant)
4. Install the BlueBubbles server (Manual Setup, Firebase optional)
5. Tailscale VPN — LAN-only HTTP option **and** `tailscale serve` TLS option
6. Tailscale Funnel (optional public-over-TLS)
7. Private API & the SIP trade-off — risks, benefits, mitigations, explicit **decision rule**, Intel + Apple Silicon steps
8. Docker-OSX self-hosting option
9. Android client checklist (bracketed `[ ]` items) + TLS verification (incl. `HandshakeException` / `CERTIFICATE_VERIFY_FAILED` log check)
10. Windows client checklist + TLS verification (PowerShell `Invoke-WebRequest` + certificate thumbprint inspection)
11. Operational hygiene & hardening
12. Appendix A — commands reference (Tailscale, SIP, verification)
13. Appendix B — troubleshooting matrix (table)
14. Sources — 11 numbered, hyperlinked entries

## 6. Source Citations (use these URLs, wrapped in `<a href="..." color="#01696F">…</a>`)

1. Tailscale blog — https://tailscale.com/blog/bluebubbles-tailscale-imessage-android-pc-no-port-forwarding
2. Manual Setup — https://docs.bluebubbles.app/server/installation-guides/manual-setup
3. Contacts fix — https://github.com/BlueBubblesApp/bluebubbles-docs/blob/master/server/troubleshooting-guides/bluebubbles-server-cannot-access-macos-contacts.md
4. Accessibility issue #792 — https://github.com/BlueBubblesApp/bluebubbles-server/issues/792
5. Standard Install — https://bluebubbles.app/install/
6. Tailscale VPN Setup (BB docs) — https://docs.bluebubbles.app/server/advanced/byo-proxy-service-guides/tailscale-vpn-setup
7. Private API Install — https://docs.bluebubbles.app/private-api/installation
8. Docker-OSX as a Service — https://docs.bluebubbles.app/server/advanced/macos-virtualization/running-bluebubbles-in-docker-osx/configuring-bluebubbles-as-a-service
9. SIP on Unofficial Macs — https://docs.bluebubbles.app/server/advanced/disabling-sip-on-unofficial-macs-for-the-private-api
10. Android CA issue #2688 — https://github.com/BlueBubblesApp/bluebubbles-app/issues/2688
11. Simplified Setup blog — https://docs.bluebubbles.app/blog/simplified-setup

## 7. Deliverables

1. `/home/user/workspace/build_bluebubbles_guide.py` — self-contained, runnable with `python build_bluebubbles_guide.py`.
2. `/home/user/workspace/BlueBubbles_Secure_Setup_Guide.pdf` — the generated PDF.
3. A short final report in chat (see §10).

If `/home/user/workspace/build_bluebubbles_guide.py` already exists, **extend it minimally** rather than rewriting. Only rewrite if the existing file is structurally incompatible with the section order in §5.

## 8. Execution Plan (follow this)

1. **Explore**
   - `list_files /home/user/workspace` and note whether `build_bluebubbles_guide.py` and `BlueBubbles_Secure_Setup_Guide.pdf` already exist.
   - `read_file build_bluebubbles_guide.py` if present.
2. **Verify deps**
   - Run `python -c "import reportlab, pypdf"`. If it fails, `pip install --user reportlab pypdf`.
3. **Design / edit**
   - Ensure fonts are fetched and registered exactly once at module load.
   - Ensure every section in §5 is present and in order.
   - Replace any Unicode checkboxes with `<font name="DMSans-Bold" color="#01696F">[ ]</font>&nbsp;&nbsp;` inline in a Paragraph.
   - Confirm `<super>N</super>` footnote markers appear in body text and each `N` has a matching line in the Sources section.
4. **Build**
   - `python /home/user/workspace/build_bluebubbles_guide.py`
5. **Verify (see §9)**
6. **Report (see §10)**

## 9. Acceptance Criteria & Guardrails

All of the following **must** pass. Run these verbatim and capture output:

```bash
cd /home/user/workspace

# a. Script runs clean
python build_bluebubbles_guide.py

# b. Metadata
pdfinfo BlueBubbles_Secure_Setup_Guide.pdf | grep -E "Title|Author|Pages|Page size"

# c. Page count is 10–20 pages
pages=$(pdfinfo BlueBubbles_Secure_Setup_Guide.pdf | awk '/Pages:/ {print $2}')
test "$pages" -ge 10 && test "$pages" -le 20 && echo "PAGE_COUNT_OK=$pages"

# d. Required strings present in extracted text
pdftotext BlueBubbles_Secure_Setup_Guide.pdf - | grep -c "tailscale serve --bg --https=443 1234"
pdftotext BlueBubbles_Secure_Setup_Guide.pdf - | grep -c "csrutil disable"
pdftotext BlueBubbles_Secure_Setup_Guide.pdf - | grep -c "CERTIFICATE_VERIFY_FAILED"
pdftotext BlueBubbles_Secure_Setup_Guide.pdf - | grep -c "Full Disk Access"
pdftotext BlueBubbles_Secure_Setup_Guide.pdf - | grep -c "Docker-OSX"

# e. No Unicode super/subscripts or stray checkbox glyphs in source
grep -Pn "[\x{2070}-\x{209F}\x{2610}\x{2611}\x{2612}]" build_bluebubbles_guide.py && echo "FAIL: unicode glyph" || echo "NO_BAD_UNICODE"

# f. Visual spot-check — render pages 1, 5, and last, confirm no errors
last=$(pdfinfo BlueBubbles_Secure_Setup_Guide.pdf | awk '/Pages:/ {print $2}')
pdftoppm -f 1 -l 1 -r 100 BlueBubbles_Secure_Setup_Guide.pdf /tmp/bb_p1 -png
pdftoppm -f 5 -l 5 -r 100 BlueBubbles_Secure_Setup_Guide.pdf /tmp/bb_p5 -png
pdftoppm -f "$last" -l "$last" -r 100 BlueBubbles_Secure_Setup_Guide.pdf /tmp/bb_plast -png
```

Expected: every `grep -c` returns ≥ 1, `PAGE_COUNT_OK` prints, `NO_BAD_UNICODE` prints, and three PNGs are produced without errors.

**Guardrails — stop and surface to the user if any of these are true:**

- A new top-level dependency other than `reportlab` or `pypdf` is needed.
- The ReportLab API surface appears to have changed (imports fail).
- Font downloads fail for all three families (Helvetica-only fallback is acceptable; note it in the report).
- Acceptance check `(e)` finds a forbidden Unicode glyph and you cannot locate/replace it.
- Any file outside `/home/user/workspace/` would be modified.

## 10. Final Report Format

Reply in chat with exactly this structure:

````markdown
**Summary:** <2–4 sentences>

**Files changed:**
- `build_bluebubbles_guide.py` — <one-line purpose>
- `BlueBubbles_Secure_Setup_Guide.pdf` — generated, <N> pages

**Verification:**
```
<pdfinfo output>
<grep counts: tailscale/csrutil/CERTIFICATE_VERIFY_FAILED/Full Disk Access/Docker-OSX>
<PAGE_COUNT_OK=…>
<NO_BAD_UNICODE>
```

**Known gaps / follow-ups:** <bullets or "none">
````

---

### Quick-fill variables

```
GOAL: Generate the BlueBubbles secure setup PDF
REPO: /home/user/workspace
LANGUAGE: Python 3.11 + ReportLab
KEY_FILES: build_bluebubbles_guide.py
TEST_CMD: python build_bluebubbles_guide.py && pdfinfo BlueBubbles_Secure_Setup_Guide.pdf
LINT_CMD: (optional) ruff check build_bluebubbles_guide.py
OFF_LIMITS: anything outside /home/user/workspace
AUTO_APPROVE: true
```
