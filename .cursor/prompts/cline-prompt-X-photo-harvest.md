# Prompt X — Photo Harvest from Apple Notes + HEIC Conversion

Read CLAUDE.md first. This prompt harvests project photos from Apple Notes
attachments, dedupes them against lovable-uploads/, and converts HEIC files.

## CONTEXT

The symphonysh website repo lives at ~/symphonysh.
All site photos go to ~/symphonysh/public/lovable-uploads/.
There are already HEIC files there that need converting.
The notes_indexer.py JXA times out when Notes has a large iCloud library —
work around this by writing a standalone AppleScript export.

## STEP 1: Convert existing HEIC files in lovable-uploads

These files already exist and MUST be converted to JPG — the website cannot
serve HEIC:

~/symphonysh/public/lovable-uploads/wiring/Wire Relocation/IMG_2841.HEIC
~/symphonysh/public/lovable-uploads/wiring/Wire Relocation/IMG_2840.HEIC
~/symphonysh/public/lovable-uploads/wiring/IMG_0444.HEIC
~/symphonysh/public/lovable-uploads/wiring/IMG_2330.HEIC
~/symphonysh/public/lovable-uploads/wiring/IMG_0443.HEIC
~/symphonysh/public/lovable-uploads/mounted tvs/Misc/IMG_0012.HEIC

For each:
  sips -s format jpeg "$heic" --out "${heic%.HEIC}.jpg"
  rm "$heic"

After conversion, update any references in src/data/projects.ts that point
to the .HEIC paths to use .jpg instead.

## STEP 2: Skip Apple Notes JXA (it times out on large iCloud libraries)

The JXA approach in notes_parser.py times out on large Notes libraries.
Instead, write scripts/photo_harvest.py that:
- Skips Notes entirely
- Focuses on what we already have: scan ~/symphonysh/public/lovable-uploads/
  for all images, build a hash index, and write a report

## STEP 3: Build hash index of existing lovable-uploads photos

scripts/photo_harvest.py should:
1. Walk ~/symphonysh/public/lovable-uploads/ recursively
2. For each image file (.jpg, .jpeg, .png, .gif, .webp, .heic):
   - Compute sha256 of first 8KB (fast dedupe signal)
   - Record: path, size, hash, folder
3. Write /tmp/photo_harvest_existing_hashes.json

## STEP 4: Write the photo harvest report

Write data/photo_harvest_report.md with:
- Total images found in lovable-uploads
- Images by folder
- HEIC files found (and converted status)
- Any near-dupes detected (same base filename in multiple folders)
- Recommendations for projects.ts coverage

## STEP 5: Update projects.ts HEIC references

After converting HEIC → JPG:
- Read ~/symphonysh/src/data/projects.ts
- Replace every .HEIC reference with .jpg
- Write back

## STEP 6: Check projects.ts coverage

Read ~/symphonysh/src/data/projects.ts and verify every image path in it
actually exists in ~/symphonysh/public/lovable-uploads/. Report any broken
paths in the harvest report.

## COMMIT

Commit to AI-Server repo:
  git add scripts/photo_harvest.py data/photo_harvest_report.md .cursor/prompts/cline-prompt-X-photo-harvest.md
  git commit -m "Add photo harvest script and HEIC conversion report"
  git push origin main

Commit to symphonysh repo:
  cd ~/symphonysh
  git add public/lovable-uploads/ src/data/projects.ts
  git commit -m "Convert HEIC to JPG — fix unservable image files"
  git push origin main
