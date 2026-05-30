# RPA Backend State Machine Test Plan

## Test Goal

Verify that WeChat customer-service control uses the low-disturbance backend state-machine path and that existing business behavior remains unchanged.

## Static Checks

Run syntax checks for touched RPA control files:

```powershell
python -m py_compile apps\wechat_ai_customer_service\scripts\run_customer_service_listener.py apps\wechat_ai_customer_service\customer_service_live_safety.py apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

## Focused Regression

Run the scheduler suite:

```powershell
python apps\wechat_ai_customer_service\tests\run_customer_service_multi_session_scheduler_checks.py
```

Required coverage:

- explicit scheduler enable works
- scheduler remains off when neither explicit enable nor live-safety inference exists
- explicit scheduler disable remains rollback
- live-safety low-risk config infers scheduler enable
- runtime tick does not wait for slow LLM
- stale reply is blocked before send
- planner uses captured messages and cannot send through RPA
- bridge send marks workflow processed state after verified send

## Broader Regression

Run existing RPA and workflow checks:

```powershell
python apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
python apps\wechat_ai_customer_service\tests\run_wechat_win32_ocr_compat_checks.py
python apps\wechat_ai_customer_service\tests\run_rpa_acceptance_report_checks.py
```

## Runtime Smoke

Before live send:

- confirm WeChat status is online
- confirm adapter is `win32_ocr`
- confirm wxauto4 is not active as default transport
- confirm operator guard/floating status can start through the managed listener
- confirm the local customer-service console state is enabled; for isolated fresh-tenant smoke scripts, seed `CustomerServiceSettings(enabled=true, reply_mode=full_auto)` to mirror a user-started listener

## Low-Risk Live Check

Use File Transfer Assistant only.

Recommended live sequence:

1. Start local services if not already running.
2. Start listener in normal managed mode.
3. Send one short test question to File Transfer Assistant.
4. Confirm only the relevant session is captured.
5. Confirm reply is sent once.
6. Confirm audit shows scheduler/RPA metadata.
7. Confirm no blank render, logout, auxiliary shell, or target-guard stop occurred.

## Stop Conditions

Stop live testing immediately if any of the following appears:

- WeChat login window
- blank render that cannot recover
- target cannot be confirmed
- send input cannot be confirmed
- unexpected non-whitelisted target
- transport risk guard stop

These conditions should route through the existing runtime handoff path.
