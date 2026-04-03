# API-3: Neural Map — Wire System Graph CLI and API

## The Problem

`knowledge/hardware/system_graph.py` has component modeling and compatibility logic already written, but there is no way to query it. It cannot be run from the command line, and it has no API endpoint. The hardware JSON files (`tvs.json`, `mounts.json`, `networking.json`, `c4_tv_driver_reference.json`) contain the product data but may not all be loaded by `system_graph.py`. The goal is to add a CLI interface, a recommendation engine, a project validation command, and an OpenClaw API endpoint — all wired to the existing compatibility logic already in the file.

## Context Files to Read First

- `knowledge/hardware/system_graph.py` (the full implementation — read every line before touching anything)
- `knowledge/hardware/tvs.json` (TV product data — understand its schema)
- `knowledge/hardware/mounts.json` (mount product data — understand its schema)
- `knowledge/hardware/networking.json` (networking gear — understand its schema)
- `knowledge/hardware/c4_tv_driver_reference.json` (Control4 driver data — understand its schema)
- `openclaw/orchestrator.py` (where the new API endpoint gets registered)
- `knowledge/hardware/ssh_mount_clearance_validation.md` (compatibility rules reference)

## Prompt

Read the existing code first — understand the component model, the compatibility checking logic, and what data structures `system_graph.py` already uses. Do not restructure the module. Add CLI entry points and the API endpoint on top of what exists.

### 1. Audit Data Loading in system_graph.py

Read the file and identify:

- Which JSON files does it currently load? Which ones is it missing?
- What is its internal component representation? (a dict, a dataclass, a graph node?)
- What compatibility checking method already exists? (e.g., `check_compatibility(a, b)`, `is_compatible(component_a, component_b)`)

After reading, ensure all four JSON files are loaded at module initialization:

```python
DATA_DIR = Path(__file__).parent

def _load_all_data():
    tvs = json.loads((DATA_DIR / "tvs.json").read_text())
    mounts = json.loads((DATA_DIR / "mounts.json").read_text())
    networking = json.loads((DATA_DIR / "networking.json").read_text())
    c4_drivers = json.loads((DATA_DIR / "c4_tv_driver_reference.json").read_text())
    return tvs, mounts, networking, c4_drivers
```

If the file already loads some of these, do not change the loading code — add the missing ones using the same pattern.

### 2. Add CLI Interface

Add an `if __name__ == "__main__":` block at the bottom of `system_graph.py` using `argparse`:

#### Command: `--check`

```bash
python system_graph.py --check "Samsung QN80F" "Sanus VLT7"
```

Output:
```
Checking: Samsung QN80F + Sanus VLT7
✓ Compatible
  Reason: VESA pattern matches (400x400mm). Weight capacity 150lbs > TV weight 78lbs. Wall type: concrete requires toggle bolts (included with VLT7).
```

Or:
```
✗ Not Compatible
  Reason: Sanus VLT7 max weight is 130lbs. Samsung QN90C weighs 162lbs. Recommend: Sanus VMPL50A (200lb capacity).
```

- Look up both component names in the loaded data (fuzzy match — partial name match is fine)
- Call the existing compatibility method
- Print a human-readable verdict with the reason
- Exit code 0 for compatible, 1 for not compatible

#### Command: `--recommend`

```bash
python system_graph.py --recommend "100-inch TV" --budget 8000
```

Output:
```
Recommendations for 100-inch TV (budget: $8,000):

TVs:
  • Samsung QN100B (100") — $3,499 — VESA 600x400
  • LG QNED99 (100") — $3,299 — VESA 600x400

Compatible Mounts for above TVs:
  • Sanus VMPL50A — $299 — fits VESA 600x400, max weight 200lbs
  • Chief PFAU — $449 — fits VESA 600x400, max weight 250lbs

Wiring:
  • HDMI 2.1 cable (10ft) — required for 8K/120hz
  • In-wall conduit recommended for 100"+ installations
```

- Filter TVs by size range (±5 inches from requested size) and budget
- For each TV, find compatible mounts using the existing compatibility logic
- Include basic wiring recommendations based on TV specs
- If no results: say so with why (no TVs in budget, no compatible mounts found)

#### Command: `--project --validate`

```bash
python system_graph.py --project topletz --validate
```

- Look for `knowledge/projects/topletz/project-config.yaml` (or similar — check what project config files exist in the project)
- Read the equipment list from the config
- Run compatibility checks on every pair of connected components
- Output a validation report:

```
Project: Topletz
Checking 12 equipment items...

✓ Living Room TV: Samsung QN85B + Sanus VLT7 — Compatible
✓ Master Bedroom TV: LG C2 65" + VideoSecu ML531BE — Compatible
✗ Theater: Sony XR-75X95K + Chief JWIN (VESA mismatch: TV is 400x300, mount requires 400x400)
  Fix: Use Chief PSMH or Sanus VMPL50A instead

Summary: 11 compatible, 1 issue found.
```

If the project config does not exist, print a useful error and show the expected format.

### 3. Ensure Cross-Referencing Between JSON Files

The compatibility engine needs to cross-reference data across files. For example:
- A TV's VESA pattern comes from `tvs.json`
- A mount's VESA compatibility comes from `mounts.json`
- A Control4 driver's supported models come from `c4_tv_driver_reference.json`

After loading all four files, build a unified component index:

```python
component_index = {}
for tv in tvs:
    component_index[tv["model"]] = {"type": "tv", "data": tv}
for mount in mounts:
    component_index[mount["model"]] = {"type": "mount", "data": mount}
```

If the existing code already builds an index or graph, use that structure — do not duplicate it.

### 4. Add OpenClaw API Endpoint

In `openclaw/orchestrator.py` (or wherever OpenClaw registers routes — read the file first):

Add a route `POST /api/compatibility-check`:

```python
@app.post("/api/compatibility-check")
async def compatibility_check(request: CompatibilityRequest):
    """
    Body: {"components": ["Samsung QN80F", "Sanus VLT7", "Chief PSMH"]}
    Returns: compatibility report as JSON
    """
    from knowledge.hardware.system_graph import SystemGraph
    graph = SystemGraph()  # use existing class name — read system_graph.py for the actual class name
    report = graph.check_multiple(request.components)
    return {"status": "ok", "report": report}
```

The response format:
```json
{
  "status": "ok",
  "report": {
    "pairs_checked": 3,
    "compatible": [
      {"a": "Samsung QN80F", "b": "Sanus VLT7", "compatible": true, "reason": "VESA match, weight OK"}
    ],
    "incompatible": [],
    "summary": "All components compatible"
  }
}
```

Use the class name and method names that already exist in `system_graph.py` — do not invent new ones.

### 5. Test with Topletz Equipment

After implementation, run:

```bash
python knowledge/hardware/system_graph.py --check "Samsung QN85B" "Sanus VLT7"
python knowledge/hardware/system_graph.py --recommend "85-inch TV" --budget 5000
python knowledge/hardware/system_graph.py --project topletz --validate
```

All three should run without errors. If Topletz project config does not exist, create a minimal one at `knowledge/projects/topletz/project-config.yaml` with 2-3 example equipment items for testing.
