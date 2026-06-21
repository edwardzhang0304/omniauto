# PR21 Post-Merge Full Acceptance Test Plan

Date: 2026-06-21

This document is the formal test guide for validating the repository after absorbing Edward Zhang's PR #21 for the add_friend module and merging it into `master`.

## Objective

Verify that the current `master` is healthy after PR #21, that the add_friend route cleanup is fully absorbed, and that prior WeChat AI customer-service optimizations still work correctly.

## Non-Negotiable Boundaries

- Do not rename public variables, CLI routes, JSON fields, env names, public function names, or externally consumed file paths during testing.
- Treat `add-friend-entry-click-plan-windows` as the current add_friend public route after PR #21.
- Do not silently reintroduce historical add_friend routes such as `add-friend-entry-click-plan` or `add-friend-entry-click-plan-windows-1080p-reference`.
- Do not bypass Brain First reply ownership, final polish, freshness/session envelope, target confirmation, or RPA safety guards.
- Do not optimize by shortening timeouts so work is cut off before a real result is produced.
- Do not run risky live WeChat actions while the window is blank, logged out, on a service-account container, in global search, or not target-confirmed.
- Live WeChat testing must proceed from low-risk to high-risk: status, passive scans, dry-run, guarded live self-QA, then add_friend calibration/live confirmation.

## Phase Gate Rule

Each phase must complete this loop before advancing:

1. Run the planned checks for the phase.
2. Record commands and results in `.codex-longrun/test-log.md`.
3. Inspect failures or suspicious output.
4. Fix only the smallest relevant issue, if code/doc changes are required.
5. Rerun the failing command.
6. Advance only when the phase passes or an explicit blocker is recorded.

## Phase 1: Git, PR, And Route Absorption Audit

Purpose:

- Confirm PR #21 is in `master`.
- Confirm the working tree is clean before testing.
- Confirm add_friend runtime exposure matches the PR #21 route contract.

Commands:

```powershell
git status --short --branch
git merge-base --is-ancestor 32c9ebfcd34cd217487a4e01984e5f054754c683 HEAD
python -c "from apps.wechat_ai_customer_service.adapters.add_friend_routes import ADD_FRIEND_MAIN_ROUTE, ADD_FRIEND_ROUTES; from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar import SIDECAR_ACTION_CHOICES; print(ADD_FRIEND_MAIN_ROUTE); print(ADD_FRIEND_ROUTES); print(tuple(x for x in SIDECAR_ACTION_CHOICES if 'add-friend' in x))"
rg -n "ADD_FRIEND_WINDOWS_1080P_REFERENCE_ROUTE|ADD_FRIEND_WINDOWS_REFERENCE_ROUTE|ADD_FRIEND_ENTRY_CLICK_ROUTE|add-friend-entry-click-plan-windows-1080p-reference|run_wechat_add_friend_entry_click_plan\.ps1|\badd-friend-entry-click-plan\b" apps/wechat_ai_customer_service/adapters apps/wechat_ai_customer_service/scripts apps/wechat_ai_customer_service/tests apps/wechat_ai_customer_service/README.md AGENTS.md
```

Pass criteria:

- `git status` is clean.
- PR #21 commit is an ancestor of `HEAD`.
- `ADD_FRIEND_MAIN_ROUTE`, `ADD_FRIEND_ROUTES`, and sidecar add_friend choices expose only `add-friend-entry-click-plan-windows`.
- Old add_friend route names do not appear as active adapters/scripts/tests runtime contracts.
- Old route names may appear only in historical docs or explicit "historical route" guard text.

## Phase 2: Static And Import Health

Purpose:

- Catch syntax/import errors in the PR #21 add_friend surface and recently optimized Win32/OCR modules.

Commands:

```powershell
python -m py_compile apps/wechat_ai_customer_service/adapters/add_friend_artifacts.py apps/wechat_ai_customer_service/adapters/add_friend_contract.py apps/wechat_ai_customer_service/adapters/add_friend_flow.py apps/wechat_ai_customer_service/adapters/add_friend_routes.py apps/wechat_ai_customer_service/adapters/wechat_connector.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/add_friend_windows.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/humanized_input.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/session_targeting.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/window_action_planning.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py
```

Pass criteria:

- Compile exits 0.
- No source file needs framework-level or naming changes to compile.

## Phase 3: Add Friend Contract And PR21 Regression

Purpose:

- Prove PR #21 is functionally absorbed.
- Prove old routes are not accidentally still advertised or called.

Commands:

```powershell
python apps\wechat_ai_customer_service\tests\run_add_friend_package_smoke.py
python apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_device_profile_checks.py
python apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
```

Pass criteria:

- Package smoke passes all checks.
- Device profile checks pass.
- Win32/OCR compatibility suite passes.
- `WeChatConnector.add_friend()` builds a `add-friend-entry-click-plan-windows` sidecar request.
- The deleted old script remains absent.

## Phase 4: Brain First, RAG, Scheduler, And Workflow Regression

Purpose:

- Verify prior optimizations and reply-quality guardrails remain intact.
- Confirm no PR21 merge side effect broke customer-service reply ownership, RAG authority, product matching, scheduler dispatch, or acceptance reporting.

Commands:

```powershell
python apps\wechat_ai_customer_service\tests\run_customer_service_brain_contract_checks.py
python apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
python apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
python apps\wechat_ai_customer_service\tests\run_rag_layer_checks.py
python apps\wechat_ai_customer_service\tests\run_product_name_matching_checks.py
python apps\wechat_ai_customer_service\tests\run_authority_gated_ai_experience_pool_checks.py
python apps\wechat_ai_customer_service\tests\run_rpa_acceptance_report_checks.py
python apps\wechat_ai_customer_service\tests\run_file_transfer_live_regression_safety_checks.py
```

Pass criteria:

- All commands pass.
- Customer-visible replies remain Brain-authored.
- AI experience/RAG remains auxiliary and non-authoritative for product facts.
- Multi-session scheduling remains isolated.
- File Transfer Assistant live regression safety defaults remain low-risk.

## Phase 5: Cloud/Auth And Local Service Baseline

Purpose:

- Verify cloud-gate assumptions through the approved local dual-port simulation before blaming code.

Commands:

```powershell
python apps\wechat_ai_customer_service\tests\run_vps_local_two_port_shared_sync_checks.py
```

Pass criteria:

- Local dual-port cloud simulation passes.
- Any `cloud_base_url_missing` outside this simulation is treated as environment precondition, not a product defect.

## Phase 6: RPA Safety And WeChat Window Preconditions

Purpose:

- Verify the real WeChat GUI is safe before any live self-QA or add_friend live action.

Commands:

```powershell
python apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py status --artifact-dir runtime\pr21_acceptance_status
python apps\wechat_ai_customer_service\adapters\wechat_win32_ocr_sidecar.py sessions --artifact-dir runtime\pr21_acceptance_sessions
```

Pass criteria:

- WeChat is online.
- Selected window is main chat compatible.
- OCR is readable.
- No blank render, login window, global search page, service-container wrong target, or foreign overlay is detected.

Stop rules:

- Stop live tests if WeChat is logged out, blank, on a security page, or not in a main chat surface.
- Recover manually or with existing explicit recovery flow before continuing.

## Phase 7: Speed Optimization Effectiveness

Purpose:

- Confirm prior speed optimizations remain active after PR21.

Test strategy:

- Run dry short-greeting and short-business flows with artifact timing enabled.
- Inspect timing fields for capture-to-Brain overlap, target_ready reuse, continuation fast path, input profile tuning, and RPA send-stage timing.
- Compare against the documented P10/P11 expectations rather than relying on subjective feel.

Suggested commands:

```powershell
python workflows\verification\wechat_customer_service\two_visible_session_customer_service_live.py --self-check
python workflows\verification\wechat_customer_service\three_visible_session_customer_service_live.py --self-check
```

Pass criteria:

- Harness self-checks pass.
- Dry artifacts expose latency/timing fields.
- No obvious regression such as missing latency traces, missing target/session fields, or disabled safety defaults.

## Phase 8: Guarded Live Customer-Service Self-QA

Purpose:

- Verify real RPA sends still work in normal customer-service scenarios.

Sequence:

1. File Transfer Assistant single-session low-risk live smoke.
2. Two-session live self-QA for `许聪` and `新数据测试`.
3. Three-session interleaved live self-QA for `许聪`, `新数据测试`, and `文件传输助手`.

Pass criteria:

- Replies are sent to the correct target/session.
- No cross-send.
- No blank render.
- No red exclamation failed send.
- No service-account/global-search misnavigation.
- No repeated fixed-pixel clicking or keyboard/mouse overlap danger signal.
- Postflight status remains online and OCR-readable.

## Phase 9: Add Friend Calibration And Live Acceptance

Purpose:

- Validate the PR21 add_friend route in the real WeChat GUI.

Sequence:

1. Run calibration-only or no-click readiness checks first.
2. Confirm plus-entry, OCR surface, operator guard, and artifact outputs.
3. Only then run a single live add_friend attempt if a valid test account is provided and the operator guard is active.

Pass criteria:

- Action route is `add-friend-entry-click-plan-windows`.
- Field validation blocks bad payload before touching UI.
- Calibration/readiness artifacts are generated in the Windows runtime scope.
- Live add_friend either completes with a structured result or stops safely with a structured error.

Stop rules:

- Do not repeatedly add the same phone number.
- Do not continue if account restriction, security validation, blank render, or wrong surface is detected.

## Final Acceptance Criteria

The current version is considered healthy only when:

- Phases 1 through 7 pass.
- Phase 8 passes when WeChat live preconditions are available.
- Phase 9 passes at least calibration/no-click readiness, and live add_friend passes if a test account is explicitly available.
- All failures have been fixed and rerun, or explicitly recorded as environment blockers.
- `.codex-longrun/progress.md`, `.codex-longrun/test-log.md`, and `.codex-longrun/state.json` are updated.

