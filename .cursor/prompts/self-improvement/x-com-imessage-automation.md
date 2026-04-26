# X.com URL automation from iMessage

## Context
The self-improvement loop detected 19 instances of X.com URLs being manually sent to the Symphony business iMessage line (+19705193013) for processing. This represents a manual workflow that should be automated.

## Current state
- notification-hub receives iMessages but doesn't process X.com URLs automatically
- x_intake exists and can process X.com URLs 
- Manual workflow: someone texts X.com URLs to business line → collected in inbox → manual processing

## Target state
- notification-hub detects X.com URLs in incoming iMessages to business line
- Automatically routes URLs to x_intake for processing
- Eliminates manual inbox collection step

## Safety constraints
- **Do not browse the web** — work only with existing code and documented APIs
- **Do not read secrets** — use environment variable patterns, don't read .env
- **Repo-local only** — no new external dependencies
- **Bounded scope** — < 200 LOC, < 10 files
- **Test with sample data** — don't send real URLs during testing

## Acceptance criteria
1. notification-hub iMessage handler detects X.com URLs in incoming messages
2. URLs from business line (+19705193013) get routed to x_intake
3. Configuration allows enabling/disabling this feature
4. Logging shows URL detection and routing
5. Updated documentation explains the automated workflow

## Implementation approach
1. Examine notification-hub iMessage handler code
2. Add X.com URL regex detection 
3. Add integration with x_intake processing
4. Add business line number filtering
5. Add logging and configuration
6. Update documentation

## Files likely to change
- notification-hub iMessage handler (likely Python)
- x_intake integration code
- Configuration files
- Documentation

## Verification
- Code review shows clean integration
- Logging demonstrates URL detection
- Configuration properly isolates business line messages
- No external API calls during implementation

This is a bounded, repo-local automation that eliminates manual toil in the current X.com URL processing workflow.