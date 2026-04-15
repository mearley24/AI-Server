## Notes Ingest v2 — Categorize + Sync

You are working on ~/AI-Server on Bob.

### Context

- `data/notes_index.json` has 504 notes from April 12, all with `category: unknown` because Ollama categorization never ran
- 393 were already ingested into Cortex uncategorized
- Ollama is on Maestro at `192.168.1.199:11434` with `llama3.1:8b` and `qwen3:8b`
- The ingest pipeline is idempotent via SHA-256 dedup so re-running is safe

### Step 1 — Re-export from NoteStore.sqlite

Pick up any notes added since April 12:

```zsh
python3 scripts/export_notes.py
```

Report how many notes are now in `data/notes_index.json`.

### Step 2 — Verify Ollama reachability

```zsh
curl -s http://192.168.1.199:11434/api/tags | python3 -c "import sys,json; [print(m['name']) for m in json.load(sys.stdin)['models']]"
```

Confirm `llama3.1:8b` is listed. If Maestro is unreachable, set `OLLAMA_HOST=http://127.0.0.1:11434` and use whatever model Bob has locally.

### Step 3 — Run the categorizer

```zsh
OLLAMA_HOST=http://192.168.1.199:11434 python3 integrations/apple_notes/notes_indexer.py --index
```

This updates `data/notes_index.json` with proper categories (install_notes, access_codes, work_procedure, etc.) instead of `unknown`. It uses Ollama for LLM classification.

If it times out or errors on Ollama calls, check:
- Is the Ollama URL correct? Test with `curl -s http://192.168.1.199:11434/api/generate -d '{"model":"llama3.1:8b","prompt":"hello","stream":false}' | head -c 200`
- If Maestro is down, fall back to Bob's local model: `OLLAMA_HOST=http://127.0.0.1:11434 NOTES_INDEXER_OLLAMA_MODEL=llama3.2:3b python3 integrations/apple_notes/notes_indexer.py --index`

After completion, verify categories are populated:

```zsh
python3 -c "
import json
from collections import Counter
d = json.load(open('data/notes_index.json'))
cats = Counter(n.get('category','unknown') for n in d['notes'])
for cat, count in cats.most_common():
    print(f'  {cat}: {count}')
unknown = cats.get('unknown', 0)
total = sum(cats.values())
print(f'\nCategorized: {total - unknown}/{total}')
"
```

Target: most notes should have a real category, not `unknown`.

### Step 4 — Re-ingest to Cortex with categories

```zsh
python3 scripts/notes_to_cortex.py
```

This will update existing Cortex entries with proper categories and ingest any new notes.

### Step 5 — Set up daily sync via launchd

Create `~/Library/LaunchAgents/com.symphony.notes-sync.plist`:

```zsh
cat > ~/Library/LaunchAgents/com.symphony.notes-sync.plist << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.symphony.notes-sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-c</string>
        <string>cd ~/AI-Server &amp;&amp; python3 scripts/export_notes.py &amp;&amp; OLLAMA_HOST=http://192.168.1.199:11434 python3 integrations/apple_notes/notes_indexer.py --index &amp;&amp; python3 scripts/notes_to_cortex.py >> /tmp/notes-sync.log 2>&amp;1</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>4</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/notes-sync.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/notes-sync.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/Users/bob/Library/Python/3.9/bin</string>
        <key>OLLAMA_HOST</key>
        <string>http://192.168.1.199:11434</string>
    </dict>
</dict>
</plist>
PLIST

launchctl load ~/Library/LaunchAgents/com.symphony.notes-sync.plist
```

Verify it loaded:

```zsh
launchctl list | grep notes-sync
```

### Step 6 — Verify Cortex

```zsh
curl -s http://127.0.0.1:8102/stats 2>/dev/null | python3 -m json.tool
```

Memory count should have increased. Check that categorized notes are present:

```zsh
curl -s "http://127.0.0.1:8102/memories?limit=5&category=install_notes" | python3 -m json.tool
```

### Output

Report:
- Total notes exported
- Categorization breakdown (how many per category)
- Cortex memory count before and after
- Launchd plist loaded successfully
- Any errors encountered

Commit and push:

```zsh
git add -A && git commit -m "feat: notes ingest v2 -- categorized + daily launchd sync" && git push
```
