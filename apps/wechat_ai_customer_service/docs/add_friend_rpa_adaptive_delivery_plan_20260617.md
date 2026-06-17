# add_friend RPA adaptive delivery plan

This document is the implementation contract for the 2026-06-17 add_friend
adaptive refactor. It builds on the current Windows main/reference split and
keeps the existing add_friend module structure intact.

## Goal

Make the add_friend RPA flow safer on machines with different resolution, DPI,
window position, and WeChat skin/layout drift.

The target direction is:

```text
device profile + layout model + semantic/OCR locator
-> candidate points with confidence and evidence
-> low-risk calibration/dry-run report
-> guarded human-paced execution
-> state evidence after every key action
```

## Non-goals

- Do not remove the current Windows framework or route structure.
- Do not turn the 1920x1080 reference route back into the official route.
- Do not add a second input-interference guard. The add_friend flow must reuse
  the existing floating-ball operator guard.
- Do not submit real friend requests during calibration.

## Phases

### Phase 0 - Baseline and Documentation

- Record the current add_friend adaptive direction.
- Keep the Windows main route and Windows 1920x1080 reference route distinct.
- Define acceptance checks before code changes expand.

Done when:

- This document exists.
- `.codex-longrun/state.json` describes this objective.

### Phase 1 - Layout Model and Device Profile

- Add a focused add_friend layout module.
- Keep locator output shaped as:
  `point`, `confidence`, `source`, `selected_reason`, `fallback_used`,
  `fallback_reason`, `candidates`, and `metadata`.
- Add device profile evidence to add_friend plans/reports:
  screen size, virtual screen, DPI, monitor count, window rect, client rect,
  screenshot size, and route kind.

Done when:

- `+` entry locator is reachable through the layout model.
- Device profile is included in add_friend payloads and review summaries.
- Existing callers remain compatible.

### Phase 2 - Invite Form Semantic Locator

- Keep `add_friend_invite_form_targets()` compatible, but allow OCR items.
- Prefer semantic/OCR anchors for:
  - verification message textarea
  - remark input
  - confirm button
- Use fixed geometry only as an explicit fallback.
- Keep field-fill evidence in the result payload.

Done when:

- Smoke tests prove semantic targets do not mark `fallback_used`.
- Geometry fallback remains available and explicit.
- Filled screenshot/ocr data includes field verification evidence.

### Phase 3 - Calibration / Dry-run Mode

- Add a calibration mode for add_friend routes.
- In calibration mode, capture, OCR, locate, annotate, and report only.
- Do not click `+`, do not type query, do not click confirm.

Done when:

- CLI/daemon can pass calibration mode.
- Calibration payload includes locator candidates, device profile, screenshots,
  OCR snapshots, and a clear `no_clicks_performed` marker.

### Phase 4 - Verification and Delivery

- Run focused syntax and smoke tests.
- Run relevant compatibility checks where practical.
- If a broad suite has an unrelated failure, document it rather than masking it.
- Update long-running logs and notify the user for review.

Done when:

- Focused tests pass.
- Longrun state is valid.
- Delivery summary identifies any remaining live-only validation boundary.

## Acceptance Matrix

| Area | Required evidence |
| --- | --- |
| Layout | `add_friend_plus_entry_target` returns model-backed candidates and confidence. |
| Device profile | Payload/review include screen, DPI, monitor, window, client, and screenshot data. |
| Invite form | OCR anchors can produce semantic locators; fixed geometry is fallback only. |
| Calibration | Dry-run produces report without UI clicks or text input. |
| Guard | Floating-ball operator guard remains the only input-interference guard. |
| Tests | py_compile and add_friend smoke pass. |

