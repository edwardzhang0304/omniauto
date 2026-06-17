# Add Friend CLI Contract Stability Plan

> Customer-service development baseline: [`customer_visible_reply_ownership_baseline.md`](customer_visible_reply_ownership_baseline.md).

## Purpose

The add-friend RPA implementation can keep evolving internally for Windows geometry, DPI scaling, OCR location, fallback click points, theme handling, and future platform adapters. The external Worker-facing CLI contract must remain stable so OmniAuto can be updated and repackaged without changing the Worker integration.

Canonical external command:

```text
add-friend-entry-click-plan
```

The command name, required arguments, exit semantics, and JSON output contract should be treated as the stable boundary. Internal routes such as Windows adaptive, Windows 1080p reference, and future macOS implementations should sit behind that boundary.

## Current State

The current implementation is functionally strong, and this plan keeps the route boundary suitable for long-term upstream compatibility.

What is already good:

- `add-friend-entry-click-plan` still exists in the sidecar action list.
- Required inputs are still validated through `validate_add_friend_entry_click_contract`.
- Stable output fields are already centralized around `task_status`, `result_code`, `error_code`, `current_step`, and `server_report_payload`.
- Package smoke tests cover validation, failure payloads, success payloads, already-friend handling, operator guard, artifacts, and route metadata.
- Windows adaptive internals now cover geometry, OCR, semantic targets, operator guard, dark/light input handling, and safer click pacing.

Compatibility gap found during audit and now addressed in the implementation:

- `ADD_FRIEND_MAIN_ROUTE` now points to `add-friend-entry-click-plan`.
- `WeChatConnector.add_friend()` now calls `add-friend-entry-click-plan`.
- `add-friend-entry-click-plan-windows` remains an explicit Windows alias for local Windows runs and migration.
- The fixed Windows 1920x1080 comparison path is explicitly named `add-friend-entry-click-plan-windows-1080p-reference`.

This means the JSON contract and the canonical CLI name now match the upstream-friendly contract suggested by the add-friend module developer.

## Target Architecture

External contract:

```text
Worker / operator script
  -> add-friend-entry-click-plan
     -> platform router
        -> windows adaptive implementation
        -> macOS implementation, future
        -> diagnostic/reference routes, internal only
```

Stable public entry:

- `add-friend-entry-click-plan`

Supported aliases:

- `add-friend-entry-click-plan-windows` may remain as a compatibility alias during migration.

Internal/reference route:

- The old fixed Windows 1920x1080 logic should not occupy the canonical public command name.
- If retained, rename or expose it as an explicit diagnostic/reference route such as:

```text
add-friend-entry-click-plan-windows-1080p-reference
```

The reference route must not be called by Worker packaging or the default connector path.

## Stable CLI Input Contract

The canonical command must keep accepting these inputs:

```text
--phone
--wechat
--verify-message
--remark-name
--remark-code
--artifact-dir
--calibration-only
```

Required formal fields:

```text
phone_or_wechat
verify_message
remark_name
remark_code
```

Compatibility rules:

- Adding optional flags is allowed.
- Removing or renaming existing flags is not allowed.
- Changing required-field meanings is not allowed.
- Internal platform selection must not require Worker changes.
- `--calibration-only` must remain non-clicking and safe for capture/OCR/locator reporting.

## Stable JSON Output Contract

These top-level fields must remain stable whenever applicable:

```text
ok
state
task_status
result_code
error_code
current_step
reason
error
artifact_dir
plan_path
review_json_path
review_html_path
server_report_payload
events
diagnostics
```

Stable business result codes:

```text
invite_sent
already_friend
```

Stable failure categories:

```text
TASK_PAYLOAD_INVALID
PHONE_NOT_FOUND
ADD_CONTACT_ENTRY_NOT_FOUND
INVITE_FORM_WINDOW_NOT_FOUND
INVITE_CONFIRM_CLICK_FAILED
ACCOUNT_RESTRICTED
WECHAT_WINDOW_NOT_READY
OPERATOR_GUARD_NOT_READY
```

Compatibility rules:

- Existing fields may be enriched but must not change meaning.
- New fields are allowed if old fields stay present.
- Failure payloads must still include `task_status=failed`, an `error_code`, and `current_step`.
- Success payloads must still include `task_status=completed`, `result_code`, and `current_step`.
- `server_report_payload` must keep the `task.*` keys used by upper layers.

## Optimization Plan

### Phase 1: Route Contract Realignment

Make `add-friend-entry-click-plan` the official main route again.

Implementation intent:

- Set `ADD_FRIEND_MAIN_ROUTE = ADD_FRIEND_ENTRY_CLICK_ROUTE`.
- Keep `ADD_FRIEND_ENTRY_CLICK_WINDOWS_ROUTE` as an alias for now.
- Move the old fixed 1920x1080 route to an explicit reference name if it still needs to be callable.
- Ensure both canonical and Windows alias dispatch into the same Windows adaptive implementation on Windows.

Expected outcome:

- Existing Worker calls to `add-friend-entry-click-plan` work.
- Existing local calls to `add-friend-entry-click-plan-windows` still work during migration.
- Reference/fixed-coordinate code is clearly non-default.

### Phase 2: Connector And Script Cleanup

Default all official add-friend callers back to the canonical command.

Files to update:

```text
apps/wechat_ai_customer_service/adapters/wechat_connector.py
apps/wechat_ai_customer_service/scripts/run_wechat_add_friend_entry_click_plan.ps1
apps/wechat_ai_customer_service/scripts/check_wechat_add_friend_entry_click_latest.ps1
```

Expected outcome:

- `WeChatConnector.add_friend()` calls `add-friend-entry-click-plan`.
- Main operator script calls `add-friend-entry-click-plan`.
- Windows alias script may remain as a lower-level explicit Windows helper.

### Phase 3: Test Contract Update

Update tests so they protect the canonical boundary instead of the temporary Windows route.

Required checks:

- `--help` includes `add-friend-entry-click-plan`.
- Canonical route accepts all required formal fields.
- Canonical route is the official main route.
- Windows alias produces equivalent contract payloads.
- Reference route, if retained, is explicitly marked diagnostic/reference.
- Worker-facing connector uses canonical route.

Existing suites to keep:

```text
python apps/wechat_ai_customer_service/tests/run_add_friend_package_smoke.py
python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py
```

### Phase 4: Upstream-Friendly Internal Adapter Boundary

Move platform-specific implementation choices behind a route/platform resolver.

Windows internals may continue changing:

- window geometry
- DPI scaling
- OCR regions
- fallback click points
- dark/light theme handling
- operator guard
- adaptive layout model
- calibration artifacts

Future macOS internals should be added as a separate adapter rather than changing the public Worker command.

### Phase 5: Worker Package Rebuild

After the route contract is stable and merged to `master`:

1. Pull latest OmniAuto.
2. Run package smoke checks.
3. Run one controlled live add-friend verification.
4. Rebuild Worker package.
5. Deploy Worker without changing its add-friend invocation.

## Acceptance Matrix

Static/package checks:

```text
python -m py_compile apps/wechat_ai_customer_service/adapters/add_friend_*.py
python -m py_compile apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py
python apps/wechat_ai_customer_service/tests/run_add_friend_package_smoke.py
python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py
```

CLI contract checks:

- `add-friend-entry-click-plan --help` exposes the stable flags.
- Missing `verify_message` returns `TASK_PAYLOAD_INVALID`.
- Missing `phone/wechat` returns `TASK_PAYLOAD_INVALID`.
- Missing or mismatched `remark_code` returns `TASK_PAYLOAD_INVALID`.
- `--calibration-only` never clicks and returns locator/artifact data.

Live checks:

- Existing friend returns `already_friend`.
- Valid new account returns `invite_sent`.
- Non-existent account returns `PHONE_NOT_FOUND`.
- Login/security prompt returns `WECHAT_WINDOW_NOT_READY` or `ACCOUNT_RESTRICTED`.
- Dark and light themes both pass input/draft detection.
- No runtime log/cache/account state is included in the Worker package.

## Definition Of Done

The optimization is complete when:

- `add-friend-entry-click-plan` is again the canonical Worker-facing main route.
- `add-friend-entry-click-plan-windows` remains a compatibility alias; reference/diagnostic behavior uses the explicit 1080p reference route.
- The old fixed 1920x1080 implementation no longer owns the canonical route name.
- Required inputs and JSON output fields are unchanged.
- Package smoke and Win32/OCR compatibility suites pass.
- At least one controlled live add-friend run passes.
- Worker can be rebuilt from latest `master` without changing its invocation.

## Developer Guidance For OmniAuto Maintainers

Recommended message:

```text
You can fix window coordinates, DPI handling, OCR localization, fallback click points, and platform-specific RPA internals inside the OmniAuto repository. Please keep the add-friend-entry-click-plan CLI inputs and JSON output contract stable. After the fix is merged to master, we can pull the latest OmniAuto and rebuild the Worker package without changing the Worker integration.
```

This keeps the collaboration boundary clean: OmniAuto owns internal RPA robustness, while Worker integration depends only on the stable CLI contract.
