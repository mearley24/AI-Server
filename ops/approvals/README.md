# ops/approvals — high-risk task approval tokens

This directory holds the files that authorize the Symphony Task Runner to
execute **high-risk tasks** (money, secrets, destructive infra,
customer-visible outbound comms, cross-host destructive changes).

Low-risk and medium-risk tasks do **not** use this directory — standing
approval covers them. Only tasks that self-declare as high risk (see below)
are gated here.

## How the gate works

`ops/task_runner_gates.py` flags a task as high-risk when any of the
following is true on the task JSON:

* `requires_approval: true` at the top level, or on `payload`.
* `risk_tier: "high"` (or `"critical"`) at the top level, or on `payload`.

A high-risk task is allowed through the gate if **one** of these is true:

1. `dry_run: true` — no side effects, so no approval needed.
2. `approval_token: "<token>"` is present AND this directory contains a
   file named `<token>.approval` (committed to the repo).
3. `approval_token == task_id` AND `task_id` is listed on its own line
   in `AUTO_APPROVE_IDS.txt`.

Otherwise the runner writes
`ops/verification/<stamp>-blocker-<task_id>.txt`, moves the task to
`ops/work_queue/blocked/`, and leaves it there until a human (or another
agent) provides the approval.

## Creating an approval file

Pick an arbitrary token string (the task_id is a fine default), then:

```bash
printf 'approved by <name> at %s\n' "$(date -u +%FT%TZ)" \
  > ops/approvals/<token>.approval
git add ops/approvals/<token>.approval
git commit -m "approval: <task-id or short description>"
git push origin main
```

The file's contents are free-form; the gate only cares that the file
exists. Keep content honest — the commit is the real audit trail.

## Deactivating an approval

Delete the `.approval` file and commit the removal. The next tick the
gate will stop honoring the token.

```bash
git rm ops/approvals/<token>.approval
git commit -m "approval: revoke <task-id>"
git push origin main
```

## AUTO_APPROVE_IDS.txt

Lists task_ids that are pre-authorized for **self-approval** — i.e. a
task whose `approval_token` equals its own `task_id`. This is appropriate
for recurring scheduled high-risk work where a human pre-approved the
*type* of operation but does not want to commit a fresh approval file
every run.

Format: one task_id per line. `#` comments allowed. Case-sensitive.

Self-approval is intentionally narrow — it only works when the token
literally equals the task_id. Anything else requires an explicit
`.approval` file.

## Security notes

* Approval files live under version control so every approval leaves a
  commit. `git log -- ops/approvals/` is the audit trail.
* The gate rejects tokens containing `/`, `..`, or leading `.` to prevent
  path-traversal escapes.
* The gate does not interpret the file contents — treat `.approval` files
  as evidence, not configuration.
