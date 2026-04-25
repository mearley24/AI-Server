# Batch processing for similar iMessage URL patterns

## Context
The self-improvement inbox frequently receives multiple iMessage items with identical patterns (same phone number, same structure, different URLs). Currently each creates an individual card, creating processing overhead.

## Scope
Enhance `scripts/self-improve.sh process` to detect and batch similar iMessage URL patterns, reducing card generation overhead while preserving audit trails.

## Requirements
1. **Pattern detection**: Detect identical iMessage patterns (same handle, same structure, only URL differs)
2. **Batch consolidation**: Group similar items into single consolidated cards
3. **Metadata preservation**: Maintain individual URLs, timestamps, and confidence levels in grouped cards
4. **Configurable limits**: Default batch size of 10, configurable via environment variable
5. **Audit trail**: Preserve link to individual archived files in consolidated cards

## Acceptance criteria
- [ ] Similar iMessage URL patterns are automatically detected
- [ ] Consolidated cards contain all individual URLs and metadata
- [ ] Individual archive files are still created (unchanged behavior)
- [ ] Batch size is configurable via `SELF_IMPROVE_BATCH_SIZE` (default: 10)
- [ ] Original card template format is preserved for consolidated cards
- [ ] Processing logic handles edge cases (different confidence levels, timeframe spans)

## Files to modify
- `scripts/self-improve.sh` (add batching logic)
- `ops/self_improvement/` processing functions
- Card generation logic

## Safety constraints
- No external API calls
- No secret/credential access
- Bounded to ops/self_improvement/ directory
- Preserve all existing archive behavior
- Maintain idempotency (same input = same output)

## Testing
- Process test inbox with multiple similar items
- Verify consolidated cards contain all URLs
- Confirm individual archives are still created
- Test with mixed patterns (some batchable, some unique)
