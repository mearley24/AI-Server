# Symphony Suite Acceptance Checklist

Status date: 2026-03-14

## Navigation + UX

- [x] Primary horizontal nav (`Today`, `Projects`, `Sales`, `Install`, `Ops`, `Settings`)
- [x] Secondary horizontal nav under primary (mode-specific)
- [x] Persistent tab/mode selection via `AppStorage`
- [x] `Projects` contains `Markup`, `SOW`, `Manual Digest`, `Room Modeler`
- [x] `Sales` contains `Pipeline` + `D-Tools Product Agent` only
- [x] `Install` cleaned to service/install queue only
- [x] `Ops` includes weather setup option

## D-Tools + SOW workflows

- [x] D-Tools product parsing supports invoice upload flow in app
- [x] Rexel invoice profile integrated in backend and iOS picker
- [x] SOW generation and export in `Projects -> SOW`

## Ops + Incident workflow

- [x] Network dropout watcher controls in app
- [x] One-tap incident creation from latest dropout event
- [x] Mode-scoped refresh optimization in Ops tab

## Security + auth UX

- [x] API Auth uses Vault-key dropdown in Settings
- [x] Selected Vault API token can be applied directly to Keychain
- [x] Save Token / One-Tap Fix now sync token to selected Vault API token key

## App split architecture

- [x] `SymphonyOps` remains suite shell/launcher
- [x] Domain root views extracted to dedicated files
- [x] New standalone app targets created:
  - [x] `SymphonyProjects`
  - [x] `SymphonySales`
  - [x] `SymphonyInstall`
  - [x] `SymphonyOpsField`
- [x] Per-target section scoping via compile flags:
  - `APP_PROJECTS`, `APP_SALES`, `APP_INSTALL`, `APP_OPS`
- [x] Per-target display names configured:
  - `Symphony Ops`
  - `Symphony Projects`
  - `Symphony Sales`
  - `Symphony Install`
  - `Symphony Ops Field`

## Build validation

- [x] `SymphonyOps` Debug simulator build passes
- [x] `SymphonyProjects` Debug simulator build passes
- [x] `SymphonySales` Debug simulator build passes
- [x] `SymphonyInstall` Debug simulator build passes
- [x] `SymphonyOpsField` Debug simulator build passes

## Supporting docs

- [x] iOS signing runbook added: `docs/IOS_SIGNING_RUNBOOK.md`
- [x] Hernaiz/Gates roll-ups generated with comparison
- [x] iOS app README updated with standalone scheme build examples
