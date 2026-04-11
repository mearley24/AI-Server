#!/usr/bin/env bash
# =============================================================================
# generate-hazel-rules.sh
# Outputs step-by-step instructions for Matt to set up Hazel rules on his M2
# so that D-Tools proposal PDFs are automatically pushed to iCloud → Bob.
#
# Usage:
#   bash scripts/generate-hazel-rules.sh
# =============================================================================

set -euo pipefail

ICLOUD_PROJECTS='~/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH/Projects'
ICLOUD_ROOT='~/Library/Mobile Documents/com~apple~CloudDocs/Symphony SH'
DTOOL_EXPORT_FOLDER=~/Documents

# ── Detect Hazel ─────────────────────────────────────────────────────────────
HAZEL_PREFS="$HOME/Library/Application Support/com.noodlesoft.Hazel"
if [ -d "$HAZEL_PREFS" ]; then
  HAZEL_STATUS="✅ Hazel is installed"
else
  HAZEL_STATUS="⚠️  Hazel NOT found — install from https://www.noodlesoft.com before proceeding"
fi

# ── Output ────────────────────────────────────────────────────────────────────
cat <<EOF
╔══════════════════════════════════════════════════════════════════════════════╗
║       Symphony Smart Homes — Hazel Rules Setup (M2 MacBook Pro)             ║
╚══════════════════════════════════════════════════════════════════════════════╝

Status: $HAZEL_STATUS

These rules auto-push D-Tools proposal PDFs to iCloud → Bob picks them up and
renames / archives / copies to Dropbox automatically.

──────────────────────────────────────────────────────────────────────────────
PREREQUISITE: Create the Projects folder in iCloud
──────────────────────────────────────────────────────────────────────────────

  mkdir -p "$ICLOUD_PROJECTS"

──────────────────────────────────────────────────────────────────────────────
RULE A — D-Tools Export Watcher
──────────────────────────────────────────────────────────────────────────────

Purpose:  Any PDF exported from D-Tools that has "Q-" in its filename gets
          copied to the shared iCloud Projects folder so Bob can process it.

Step 1:   Open Hazel → click the "+" at the bottom of the folder list.
Step 2:   Add this folder:
            $DTOOL_EXPORT_FOLDER
          (Adjust to wherever D-Tools saves exports — check D-Tools Settings
          → Export Preferences if unsure.)

Step 3:   Click "+" to add a new rule. Name it: "D-Tools → iCloud"

Step 4:   Set CONDITIONS (All of the following):
            • Kind      is    PDF
            • Name      contains    Q-

Step 5:   Set ACTIONS (in order):
            1. Copy  →  to folder:  $ICLOUD_PROJECTS
            2. (Optional) Add green colour label  →  so you can see what was sent

Step 6:   Click OK / Save.

──────────────────────────────────────────────────────────────────────────────
RULE B — Duplicate Cleanup
──────────────────────────────────────────────────────────────────────────────

Purpose:  When iCloud syncs a file that already exists, macOS creates a
          duplicate with " (1)" or " copy" in the name. This rule deletes
          those before Bob sees them so we don't process duplicates.

Step 1:   In Hazel, add this folder:
            $ICLOUD_ROOT

Step 2:   Click "+" to add a new rule. Name it: "Delete iCloud duplicates"

Step 3:   Set CONDITIONS (Any of the following):
            • Name    contains    (1)
            • Name    contains    copy
            AND
            • Kind    is    PDF

Step 4:   Set ACTIONS:
            1. Move to Trash
               (or "Delete immediately" if you prefer no recycle-bin safety net)

Step 5:   Click OK / Save.

──────────────────────────────────────────────────────────────────────────────
RULE C — Optional: Auto-open in Preview after copy
──────────────────────────────────────────────────────────────────────────────

If you want to review the PDF right after it's sent to iCloud:

  Add this action AFTER the copy action in Rule A:
    Open with: Preview.app

──────────────────────────────────────────────────────────────────────────────
TESTING
──────────────────────────────────────────────────────────────────────────────

  1. Export any proposal from D-Tools as a PDF (file must contain "Q-").
  2. Hazel should copy it to: $ICLOUD_PROJECTS
  3. iCloud syncs it to Bob within ~60 seconds.
  4. On Bob, check /tmp/file-watcher.log:
       tail -f /tmp/file-watcher.log
  5. The file should appear in:
       ~/Library/CloudStorage/Dropbox-Personal/[ProjectName]/Client/
       renamed to: "Symphony Smart Homes - [Address] - Proposal.pdf"
  6. Matt should receive an iMessage with the Dropbox share link.

──────────────────────────────────────────────────────────────────────────────
TROUBLESHOOTING
──────────────────────────────────────────────────────────────────────────────

• Hazel not triggering?
    → Make sure Hazel System Extension is allowed: System Settings → Privacy &
      Security → Extensions → Hazel Folder Actions.

• File appears in iCloud but Bob doesn't process it?
    → Check Bob's file-watcher log:  tail -f /tmp/file-watcher.log
    → Verify the file-watcher service is running:
        curl http://127.0.0.1:8102/health

• Duplicate not deleted?
    → Rule B watches the parent SymphonySH folder. Hazel only fires on direct
      children — make sure duplicates land in that folder, not a sub-folder.

• D-Tools exports to a different folder?
    → Update Rule A's watched folder. D-Tools Settings → Export Preferences →
      note the "Default Export Path".

──────────────────────────────────────────────────────────────────────────────
ADDING NEW PROJECTS
──────────────────────────────────────────────────────────────────────────────

Edit services/file-watcher/projects.json on Bob, then restart the service:

  docker restart file-watcher
  # or, if using LaunchAgent:
  launchctl stop com.symphony.file-watcher && launchctl start com.symphony.file-watcher

EOF
