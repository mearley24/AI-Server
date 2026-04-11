# Prompt W — pull.sh Hardening (Round 2)

Read CLAUDE.md first. STATUS_REPORT.md flagged pull.sh hardening as P2. The current script is 50 lines and handles the basics (stash, pull, conflict scan, auto-rebuild). This prompt finishes the job from close-all-gaps Task 5.

## CURRENT STATE

`scripts/pull.sh` currently does:
1. Checkout data files that always conflict
2. Auto-commit local changes
3. Stash + pull --rebase (with fallback to --no-rebase)
4. Stash pop
5. Scan for merge conflict markers, auto-fix by resetting to origin/main
6. Restart openclaw + cortex
7. Rebuild polymarket-bot if its code changed
8. Rebuild any service whose directory changed in the last commit

## ADDITIONS

### 1. Python syntax validation after pull

After pulling and before restarting services, verify every Python file compiles:

```zsh
echo "Validating Python syntax..."
BROKEN=""
for dir in openclaw email-monitor notification-hub integrations cortex client-portal; do
  if [ -d "$dir" ]; then
    for pyfile in $(find "$dir" -name "*.py" -type f); do
      if ! /opt/homebrew/bin/python3 -m py_compile "$pyfile" 2>/dev/null; then
        echo "  SYNTAX ERROR: $pyfile"
        BROKEN="$BROKEN $pyfile"
      fi
    done
  fi
done

if [ -n "$BROKEN" ]; then
  echo "Broken files detected. Resetting to origin/main:"
  for f in $BROKEN; do
    git checkout origin/main -- "$f" 2>/dev/null && echo "  Reset: $f"
  done
  echo "Re-run pull.sh after investigating these files."
fi
```

### 2. Auto docker compose up on compose file changes

If `docker-compose.yml` or any `Dockerfile` changed in the pull, run a full compose up:

```zsh
compose_changed=$(git diff --name-only HEAD~1 HEAD 2>/dev/null | grep -E "docker-compose\.yml|Dockerfile" || true)
if [ -n "$compose_changed" ]; then
  echo "Compose/Dockerfile changed — running full compose up..."
  docker compose up -d --build 2>/dev/null || true
fi
```

### 3. --verify flag

Add a `--verify` flag that runs the smoke test after pulling:

```zsh
if [ "${1:-}" = "--verify" ]; then
  echo ""
  echo "Running smoke test..."
  if [ -x "scripts/smoke-test.sh" ]; then
    bash scripts/smoke-test.sh
  else
    echo "smoke-test.sh not found or not executable"
  fi
fi
```

### 4. Log what changed

After pull, show a brief summary of what came in:

```zsh
echo ""
echo "Changes pulled:"
git log --oneline HEAD~3..HEAD 2>/dev/null || echo "  (no new commits)"
echo ""
echo "Files changed in last commit:"
git diff --stat HEAD~1 HEAD 2>/dev/null || echo "  (unable to diff)"
```

### 5. Safety: warn on local Python changes

Before pulling, if any Python files have uncommitted local changes, warn:

```zsh
local_py_changes=$(git diff --name-only -- '*.py' 2>/dev/null)
if [ -n "$local_py_changes" ]; then
  echo "WARNING: Local Python changes detected (will be stashed):"
  echo "$local_py_changes" | sed 's/^/  /'
fi
```

## IMPLEMENTATION

Edit `scripts/pull.sh` in place. Keep the existing logic, add the new sections in the right order:

1. Warn about local Python changes (before stash)
2. Existing: checkout data files, auto-commit, stash, pull, stash pop, conflict scan
3. NEW: Python syntax validation
4. Existing: auto-rebuild changed services
5. NEW: auto compose up on Dockerfile/compose changes
6. NEW: log what changed
7. NEW: --verify flag at the end

Target: ~90-110 lines. Keep it readable with clear section comments.

## VERIFICATION

```zsh
# Test the script runs clean
bash scripts/pull.sh

# Test with --verify flag
bash scripts/pull.sh --verify

# Verify it's executable
ls -la scripts/pull.sh
```

Commit and push:
```zsh
git add scripts/pull.sh
git commit -m "Harden pull.sh — py_compile validation, compose auto-up, --verify flag"
git push origin main
```
