# Codex Project Rules

## Windows Encoding Safety

This project may contain Chinese text. Treat all source files as UTF-8.

- Prefer `apply_patch` for manual source edits.
- Do not rewrite source files with Windows PowerShell 5.1 text pipelines such as:
  - `Get-Content file | Set-Content file`
  - `Out-File`
  - `>`
  - `>>`
- This applies especially to `.js`, `.ts`, `.tsx`, `.vue`, `.html`, `.css`, `.json`, `.py`, and `.md` files.
- If a bulk rewrite is required, explicitly read and write UTF-8 without BOM, or use Node.js `fs` APIs with `utf8`.
- After editing frontend JavaScript or TypeScript files, run `node --check`, lint, or the relevant project test command.

## WeChat Cloud Simulation Baseline (Required)

For `apps/wechat_ai_customer_service`, the test environment has an approved local cloud simulation mode:

- When real VPS/cloud is unavailable, default to local dual-port simulation (`vps_admin` + `admin_backend`) for cloud-link validation.
- Prefer running `apps/wechat_ai_customer_service/tests/run_vps_local_two_port_shared_sync_checks.py` before diagnosing cloud-gate failures.
- Under `WECHAT_CLOUD_REQUIRED=1`, `cloud_base_url_missing` means environment precondition is not satisfied, not a product bug by itself.
- Do not report cloud-gate lock as a code defect unless it also fails under:
  - local dual-port simulation, or
  - a real reachable VPS base URL.
- For live regression scripts, if bootstrap is blocked by `cloud_authoritative_access_required` + `cloud_base_url_missing`, classify as expected environment block and fix the connection path first.

## WeChat AI Customer Service Brain First Baseline (Required)

For `apps/wechat_ai_customer_service`, customer-facing reply work must follow the Brain First architecture documented under `apps/wechat_ai_customer_service/docs/brain_first_customer_service_20260603/`.

Core rule: normal customer-service replies should be designed around an LLM customer-service brain that understands the customer message, plans the reply, cites allowed evidence, then passes through guard verification and final visible polish. Do not keep solving reply-quality defects by adding more local hard-coded response branches.

- Treat `customer_service_brain` / guarded LLM synthesis as the intended owner of normal dialogue understanding, intent resolution, fuzzy entity matching, context handling, customer objections, social small talk, and final reply strategy.
- Treat product master as the highest authority for product facts such as product name, aliases, price, stock, year, mileage, condition, location, and availability.
- Treat formal knowledge as the highest authority for policies, processes, risk boundaries, financing, trade-in, after-sales, transfer, contracts, invoices, and handoff rules.
- Treat current conversation facts as valid only inside the current conversation context.
- Treat AI experience pool, historical chats, style memory, and real chat examples as auxiliary style/experience material only. They must not authorize product facts, prices, stock, condition, policies, or commitments.
- Treat LLM common sense as auxiliary reasoning only. It may support general tradeoff analysis and clearer recommendations, but it must not invent product facts or business commitments.
- Keep all customer-visible replies behind guard verification and final visible LLM polish. Do not add speed shortcuts that bypass final polish for greetings, short replies, explicit price questions, or simple answers.
- Demote RAG/realtime/local route logic to evidence retrieval, risk classification, latency profile selection, system-error handling, and fallback. Normal business replies should not be finalized by local templates when Brain First is enabled.
- Do not hard-code account-specific products, prices, car models, or sales answers in route code. Product-specific facts must come from product master or product-scoped formal knowledge.
- Preserve multi-session isolation: every captured message, Brain input, ready reply, and send operation must remain bound to the correct conversation/target/session. Before RPA sends a reply, re-check that the active WeChat conversation matches the reply target.
- OCR or RPA speaker labels such as contact names, group sender names, and chat titles are metadata, not customer message content. Apply this rule consistently to both WeChat AI customer service and AI smart recorder flows.
- When modifying reply logic, include tests for short greetings, explicit product questions, fuzzy names/typos, context follow-ups, customer objections, off-topic friendly redirection, authority-source conflicts, and multi-session no-cross-send behavior.
- If a change touches cloud gate or live startup, use the local cloud simulation baseline above before reporting a cloud authorization failure as a product defect.

## Local Test Secrets Policy (Project-Specific Override)

For `apps/wechat_ai_customer_service` local/test migration workflows, the repository owner explicitly allows plaintext test credentials in runtime/test artifacts when needed for direct environment migration and replay.

- Do **not** auto-redact or auto-remove plaintext test keys/tokens from local runtime/test files unless explicitly requested by the user in that task.
- Treat this as an intentional test-environment decision, not an automatic bug.
- Scope: local runtime/test artifacts and migration payloads only.
- Production/public release hardening is still a separate step and must be requested explicitly.
