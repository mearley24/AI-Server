# Auto-28 · Context Preprocessor

A local web tool that takes raw text (terminal output, logs, emails, tracebacks, JSON) and returns a clean, credit-efficient prompt ready to paste into Perplexity Computer.

**Port:** 8028

---

## What It Does

Raw text goes in. The tool runs this pipeline:

1. **ANSI stripping** — removes all escape codes (`\x1b[...m` etc.) from terminal output
2. **Whitespace normalization** — collapses multiple blank lines, trims trailing spaces
3. **Smart truncation** — if input > 100 lines, keeps first 10 + last 10 + any signal lines (error/warning/fail/success/traceback) from the middle; inserts a `[...N lines trimmed...]` placeholder
4. **Format detection** — auto-detects: terminal output, JSON, Python traceback, Docker logs, git output, email, general text
5. **Docker/structlog processing** — for JSON-per-line structlog: extracts event + level + timestamp + error fields, deduplicates repeated events (shows `[×N]` count)
6. **Prompt wrapping** — wraps content in:
   ```
   Context: [detected format]
   ---
   [cleaned content]
   ---
   Task: 
   ```

The UI shows character/line counts for input and output, estimated credit savings (% reduction), and lines trimmed.

---

## Running Standalone (no Docker)

**Requirements:** Python 3.9+

```bash
cd context-preprocessor
pip install flask
python app.py
```

Then open: [http://localhost:8028](http://localhost:8028)

### Dev mode (auto-reload)

```bash
FLASK_DEBUG=true python app.py
```

---

## Running with Docker

```bash
cd context-preprocessor
docker build -t context-preprocessor .
docker run -d \
  --name context-preprocessor \
  --restart unless-stopped \
  -p 0.0.0.0:8028:8028 \
  -e TZ=America/Denver \
  context-preprocessor
```

Then open: [http://bob.local:8028](http://bob.local:8028) (or your Mac Mini's IP)

---

## Adding to an Existing docker-compose.yml

Copy the snippet from `docker-compose-snippet.yml` into your existing `docker-compose.yml`:

```yaml
services:
  # ... your other services ...

  context-preprocessor:
    build:
      context: ./context-preprocessor
    container_name: context-preprocessor
    restart: unless-stopped
    ports:
      - "0.0.0.0:8028:8028"
    environment:
      - TZ=America/Denver
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "5"
```

Make sure the `context-preprocessor/` directory is a sibling of your `docker-compose.yml`.

Then:

```bash
docker compose up -d context-preprocessor
```

---

## File Structure

```
context-preprocessor/
├── app.py                    # Flask app (port 8028)
├── preprocessor.py           # Core processing pipeline
├── templates/
│   └── index.html            # UI (dark theme, vanilla JS)
├── requirements.txt          # flask
├── Dockerfile
├── docker-compose-snippet.yml
└── README.md
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+Enter` / `Cmd+Enter` | Process input |
| `Tab` (in input) | Insert 2 spaces (no focus loss) |

---

## Notes

- No database, no auth, no external API calls.
- All processing is pure Python, runs offline.
- The `Task:` field at the end of the output is intentionally left blank — fill it in before pasting into Computer.
