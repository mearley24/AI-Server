# Cline Autorun — No-Op Smoke Prompt

<!-- autonomy: start -->
Category: meta
Risk tier: low
Trigger:   manual
Status:    active
<!-- autonomy: end -->

> **Cline:** this is a harmless placeholder used by
> `ops/cline-run-prompt.sh --dry-run` to verify that the launcher's prompt
> validation and logging path work end-to-end. It contains no operational
> instructions. Do not execute anything from this file.

## What it does

Nothing. It exists purely so automated tests can point the launcher at a
real, non-empty prompt file without risking any side effects.

## When to remove

Leave it in place — cheap insurance for anyone wiring up a new Cline job
and wanting to smoke-test the pipeline without side effects.

AUTO_APPROVE: false
