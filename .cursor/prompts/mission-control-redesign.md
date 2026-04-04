# Mission Control — Compact Apple-Style Tile Redesign

## Problem
The current dashboard panels are too large and spaced out. On mobile it's unusable, and even on desktop there's wasted space everywhere. The "nothing to show" empty states are giant.

## Design Direction
Think **Apple Home app tiles** / **iOS widget grid** — compact, information-dense, rounded tiles that look great on any screen size. Every pixel earns its place.

## Rules

### Layout
- **CSS Grid with auto-fill**: tiles flow naturally, no fixed 3x2. Use `grid-template-columns: repeat(auto-fill, minmax(320px, 1fr))` so it reflows from 3 cols → 2 → 1 naturally
- Tiles should feel like cards, not full panels — `border-radius: 16px`, subtle background, no heavy borders
- **Max tile height ~280px** with overflow scroll inside if needed. No tile should dominate the viewport
- Gap between tiles: `12px`
- Page padding: `16px` on mobile, `24px` on desktop
- The topbar should be slim — 44px height max

### Typography & Density
- Panel headers: 11px uppercase label, not 14px
- Data values: keep them punchy — the P&L hero number can be 28px max, not 32px
- Service dots and names: tighter, 10-11px. The service grid should fit all 12 services without scrolling
- Email/calendar/followup items: compact rows, 32-36px height each, not 48px+
- Empty states: just a single line of muted text, no giant icons. `"No emails"` not a big envelope icon + paragraph

### Visual Style
- Background: `#000000` (true black like iOS dark mode)
- Tile background: `#1c1c1e` (Apple dark card)
- Tile border: `none` — use subtle shadow or 1px `rgba(255,255,255,0.06)` border
- Border radius: `16px` on tiles, `10px` on inner elements
- Accent stays teal `#2dd4bf`
- Font: SF Pro (system) first, Inter fallback: `font-family: -apple-system, 'SF Pro Display', 'SF Pro Text', 'Inter', system-ui, sans-serif`
- Mono: `'SF Mono', 'JetBrains Mono', monospace`

### Topbar
- Slim: 44px, true black background
- Left: small logo + "Mission Control" in 13px semibold
- Right: clock (mono, 12px) + WS dot (6px)
- No uptime badge — cut it

### Event Strip
- Slim: 28px, sits at bottom
- Single line: `[employee] event` in 10px mono
- Or remove entirely if it clutters mobile — the WS dot is enough

### Tiles

**Service Health**: 3-column grid of tiny service pills inside the tile. Each pill is just: `[dot] Name [:port]` in a single compact row. All 12 should fit without scrolling.

**Trading P&L**: Hero number top-center. Below it, 3 mini stats inline (Deposited / Returned / Open). Below that, the category bar chart — keep it compact, ~120px height max.

**Email Queue**: Compact list rows. If empty: just gray text `"No recent emails"`. No icon.

**Calendar**: Compact event rows with colored left border. If empty: `"No events today"`.

**Follow-ups**: Priority-sorted compact rows. If empty: `"No pending items"`.

**System**: CPU/Memory/Disk as thin progress bars (4px height), inline label + percentage. Below: 2-column grid of container status pills (same style as service health). Employee status as subtle text row at bottom.

### Mobile (< 600px)
- Single column
- Tiles go full-width with 12px margin
- Topbar: hide clock, just show logo + WS dot
- Event strip: hide on mobile
- Touch targets: min 44px for anything interactive

## Implementation
Edit `mission_control/static/index.html` in place. Keep all the existing JavaScript fetch logic and API calls — only redesign the HTML structure, CSS, and how data renders into the DOM. Don't change any API URLs or refresh intervals.

After editing, rebuild:
```bash
docker compose build mission-control && docker compose up -d mission-control
```
