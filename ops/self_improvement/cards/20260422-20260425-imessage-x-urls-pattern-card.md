# Improvement card — iMessage X.com URL ingestion pipeline

- **Source stream:** `imessage.chat.db`
- **Source kind:** imessage
- **Original URL:** multiple (14 X.com URLs from various accounts)
- **Original excerpt:** handle=+19705193013 is_from_me=0
text=https://x.com/[various]/status/[various]?s=42
- **Captured:** 2026-04-22 through 2026-04-25
- **Origin confidence:** medium
- **Status:** needs fetch

## Automation hypothesis
If we implemented an iMessage X.com URL ingestion pipeline, AI-Server would be able to automatically fetch, classify, and route interesting content shared via the Symphony phone number instead of manually discovering and reviewing each shared URL individually.

## Efficiency lever
Faster feedback loop — currently X.com URLs shared via iMessage to Symphony sit unprocessed until manual discovery. An automated pipeline would enable real-time processing and potential integration with the existing x_intake system.

## Affected subsystem
`integrations/x_intake` and `email-monitor` (or new `imessage-intake` service)

## Impact / Effort / Risk
- Impact: 3 — significant value if customers/contacts regularly share relevant content via iMessage
- Effort: 4 — requires iMessage bridge integration, URL fetching, and classification logic
- Risk:   4 — processing customer communications automatically could mishandle sensitive content

## Recommended next action
`needs fetch` — need to analyze actual content of the 14 URLs to determine if they contain valuable signals

## Safe next prompt
not drafted — action was not auto-safe

## Can this be auto-run?
No — requires Matt because this involves processing customer communications through the business phone number, which requires business context and approval for automation approach.
