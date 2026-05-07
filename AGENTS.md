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
