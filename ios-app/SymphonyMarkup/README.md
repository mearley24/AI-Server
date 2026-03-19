# Symphony Markup - iOS App

Dedicated iOS wrapper app for the existing markup tool.

This app is intentionally isolated from the current web markup stack:

- It does not change `tools/markup_app/web/index.html`
- It does not change `tools/markup_app/server.py` behavior
- It only hosts the existing tool inside a native iOS shell (`WKWebView`)

## Stage 1.1 Native Bridges

- Import `.symphony` from Files (toolbar download icon)
- Export/share current project state as `.symphony` (toolbar share icon)
- Open-in-place support for `.symphony` files (tap in Files -> Open in SymphonyMarkup)
- Native local-first toggle in Settings (`Enable Team Share` is OFF by default)

These bridges call existing in-page functions and do not modify the web tool logic.

## Default Endpoint

- `http://bobs-mac-mini:8091`

You can change this in app Settings.

## Build

```bash
open ios-app/SymphonyMarkup/SymphonyMarkup.xcodeproj
```

## Notes

- Use this app for native launch/connection management while keeping the current tool intact.
- If local network hostname changes, update URL in Settings.
- Local-only mode is default. Enable Team Share in iOS Settings only when collaboration/review is needed.

