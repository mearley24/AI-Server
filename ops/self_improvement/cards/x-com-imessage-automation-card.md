# Improvement card — Automated X.com URL processing from iMessage

- **Source stream:** `imessage.chat.db`
- **Source kind:** imessage
- **Original URL:** https://x.com/[various-handles]/status/[various-ids]?s=42
- **Original excerpt:** handle=+19705193013 is_from_me=0 text=https://x.com/[handle]/status/[id]?s=42
- **Captured:** 20260422T111725Z to 20260425T183942Z (19 instances)
- **Origin confidence:** medium
- **Status:** auto-safe

## Automation hypothesis
If we implemented automatic X.com URL processing from iMessage, AI-Server would be able to extract, analyze, and route X.com content automatically instead of manually collecting URLs in the self-improvement inbox. The system could detect X.com URLs in incoming iMessages to the business line, fetch the content via x_intake, and route to appropriate handlers (trading signals, news analysis, client research, etc.).

## Efficiency lever
Less human toil - eliminates manual step of sending X.com URLs to a business iMessage line for later processing. Currently someone is manually texting URLs to +19705193013 which then get collected and require manual review. An automated pipeline would immediately process these URLs through the existing x_intake system.

## Affected subsystem
`integrations/x_intake` and `notification-hub` (iMessage bridge integration)

## Impact / Effort / Risk
- Impact: 4 — high operational efficiency gain, eliminates manual URL forwarding workflow
- Effort: 3 — requires iMessage bridge integration with x_intake, moderate complexity
- Risk:   2 — repo-local integration, no new external dependencies

## Recommended next action
`auto-run via ai-dispatch` — bounded, repo-local, drafted prompt below

## Safe next prompt
`bash scripts/ai-dispatch.sh run-prompt .cursor/prompts/self-improvement/x-com-imessage-automation.md`

Scope:
- Add X.com URL detection to notification-hub iMessage handler
- Route detected X.com URLs to x_intake processing pipeline
- Add configuration for business line number filtering
- Update documentation for the automated workflow
- Test with sample URLs

## Can this be auto-run?
Yes — auto-safe, bounded, no secrets, dispatcher-gated.