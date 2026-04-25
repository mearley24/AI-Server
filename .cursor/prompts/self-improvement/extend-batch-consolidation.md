# Extend self-improvement batch consolidation for recurring patterns

You are Claude Code working in the AI-Server repo. Your job is to enhance the self-improvement inbox processing to better handle recurring patterns like the iMessage X.com URL batches.

## Context

The self-improvement processor currently creates individual cards for each iMessage X.com URL, but when we get batches of 4+ identical patterns on the same timestamp, this creates unnecessary processing overhead. The 20260425T131753Z batch had 4 nearly identical items that could be consolidated.

## Task

Enhance `ops/self-improvement/` processing to:

1. **Pattern detection** — identify when multiple inbox items share identical structure (same source, same URL pattern, same timestamp)

2. **Smart consolidation** — when 3+ items match a pattern within the same capture window (±5 minutes), create:
   - One consolidated card addressing the automation opportunity
   - Individual reference cards that point to the consolidated card
   - Preserve full audit trail of all URLs

3. **Configurable thresholds** — add settings for:
   - Minimum items for consolidation (default: 3)
   - Time window for grouping (default: 5 minutes)
   - Maximum batch size (default: 10)

## Acceptance criteria

- [ ] Multiple similar iMessage X.com URLs get consolidated automatically
- [ ] Individual URLs are preserved for audit trail
- [ ] Consolidation only happens when it reduces actual processing overhead
- [ ] No loss of information compared to individual processing
- [ ] Processing time for pattern-heavy batches is measurably reduced

## Safety requirements

- Do not modify files outside `ops/self_improvement/`
- Do not change existing card format, only improve batch processing
- Do not connect to external services
- Test changes on existing archived data before processing new items
- Preserve backward compatibility with existing scripts

## Files likely involved

- `scripts/self-improve.sh` (processing logic)
- Potentially new helper under `ops/self_improvement/`
- Update documentation if needed

## Current pattern example

The 20260425T131753Z batch shows the exact pattern:
- 4 identical iMessage captures
- Same timestamp
- All X.com URLs  
- All from +19705193013
- Same confidence level

This should become 1 consolidated card + 4 reference cards instead of 4 full cards.