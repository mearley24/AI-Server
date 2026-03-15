# iOS Signing Runbook (SymphonyOps)

This runbook is the quick path to recover from common Xcode signing failures for `SymphonyOps`.

## Scope

- App target: `ios-app/SymphonyOps`
- Typical errors:
  - `Command CodeSign failed with a nonzero exit code`
  - `No Account for Team`
  - Provisioning profile / certificate mismatch

## Fast Recovery Checklist

1. Open `ios-app/SymphonyOps/SymphonyOps.xcodeproj` in Xcode.
2. Select target `SymphonyOps` -> **Signing & Capabilities**.
3. Confirm:
   - Team is selected.
   - Bundle ID is unique and expected.
   - `Automatically manage signing` is enabled.
4. In Xcode Settings -> Accounts:
   - Remove stale Apple ID sessions if needed.
   - Re-authenticate your Apple ID.
5. Clean derived data:
   - Xcode: Product -> Clean Build Folder.
6. Rebuild:
   - Select an iOS Simulator/device and build again.

## If Development Certificate Was Revoked

If Xcode UI does not allow deleting a broken cert:

1. Open **Keychain Access**.
2. In `login` keychain, search for `Apple Development`.
3. Delete revoked/duplicate certs and matching private keys.
4. Re-open Xcode -> Accounts -> **Manage Certificates**.
5. Create a fresh `Apple Development` certificate.
6. Rebuild project.

## Team / Provisioning Reset

If signing still fails:

1. Temporarily toggle `Automatically manage signing` OFF then ON.
2. Change team to another available team (if any), then switch back.
3. Re-select connected device/simulator.
4. Build once on simulator, then again on physical device.

## CLI Validation

Run from repo root:

```bash
xcodebuild -project "ios-app/SymphonyOps/SymphonyOps.xcodeproj" -scheme "SymphonyOps" -sdk iphonesimulator -configuration Debug build
```

If this succeeds but device build fails, issue is usually provisioning/device trust, not source code.

## Notes

- Do not commit secrets/cert exports into the repo.
- Keep this runbook updated when Apple/Xcode signing flows change.
