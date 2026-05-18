# Product Master Split Test And Acceptance Plan

Date: 2026-05-16

## Static Checks

```powershell
python -m py_compile <touched python files>
node --check apps/wechat_ai_customer_service/admin_backend/static/app.js
git diff --check -- <touched files>
```

## Focused Tests

```powershell
python -u apps/wechat_ai_customer_service/tests/run_product_master_split_checks.py
python -u apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py
python -u apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter readonly
python -u apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter candidates
```

## Core Regression

```powershell
python -u apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py
python -u apps/wechat_ai_customer_service/tests/run_knowledge_compiler_checks.py
python -u apps/wechat_ai_customer_service/tests/run_knowledge_base_migration_checks.py
python -u apps/wechat_ai_customer_service/tests/run_smart_recorder_checks.py
python -u apps/wechat_ai_customer_service/tests/run_rag_boundary_checks.py
python -u apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
```

## Chejin Regression

```powershell
python -u apps/wechat_ai_customer_service/tests/run_jiangsu_chejin_used_car_checks.py
python -u apps/wechat_ai_customer_service/tests/run_jiangsu_chejin_llm_synthesis_checks.py
python -u apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py
```

## Live WeChat Acceptance

```powershell
python -u apps/wechat_ai_customer_service/tests/run_jiangsu_chejin_live_conversation_flow.py --delay-seconds 1.6 --flow-limit 3
```

Acceptance expectations:

- Product recommendations still use real product master vehicles.
- Product facts are not sourced from RAG candidates.
- Boundary questions still use hidden handoff wording.
- Anti-AI-exposure behavior remains intact.
- No formulaic reply hits.
- No foreground LLM/token regression for local real-time cases.

## Pass Criteria

- All focused checks pass.
- Full reasonable regression passes.
- Live flow passes or is explicitly blocked by unavailable WeChat/runtime environment.
- If a test exposes an actual product-master boundary bug, fix and rerun before delivery.
