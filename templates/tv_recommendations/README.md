# TV & Mount Recommendations — Template System

## Overview
Config-driven PDF generator for client TV & mount recommendation documents.
Bob feeds in a JSON config, the generator produces the full branded PDF.

## Usage

### Command line:
```bash
python generate.py config.json
```

### Programmatic:
```python
from generate import build_pdf
build_pdf(config_dict, output_path="output.pdf")
```

## Files
- `generate.py` — Main PDF generator (ReportLab)
- `config_schema.json` — JSON schema defining the config format
- `example_config.json` — Example config from Topletz 84 Aspen Meadow project
- `README.md` — This file

## Workflow
1. Bob receives client TV schedule
2. Bob runs C4 driver check against `/c4_tv_driver_reference.json`
3. Bob runs mount clearance validation against `/ssh_mount_clearance_validation.md`
4. Bob builds config JSON with client data, alternatives, and packages
5. Bob runs `python generate.py config.json` to produce the PDF
6. Bob pushes PDF to Dropbox `Projects/[Project]/Client/` folder
7. Bob verifies file exists, generates share link
8. Bob drafts email in Zoho with link, holds for Matt's review

## Related Files
- `/c4_tv_driver_reference.json` — C4 driver compatibility database
- `/c4_tv_driver_reference.md` — Human-readable driver reference
- `/ssh_mount_clearance_validation.md` — Mount validation checklist
- `/ssh_tv_mount_recommendations_playbook.md` — Full operations playbook
