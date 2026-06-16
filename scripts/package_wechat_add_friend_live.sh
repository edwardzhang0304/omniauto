#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-/Users/zhangwentao/Documents/车金/deliverables/omniauto-add-friend-rpa-clean.zip}"
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/omniauto-add-friend-package.XXXXXX")"
PACKAGE_DIR="$WORKDIR/omniauto-add-friend-rpa"

cleanup() {
  rm -rf "$WORKDIR"
}
trap cleanup EXIT

mkdir -p "$PACKAGE_DIR/apps/wechat_ai_customer_service/adapters"
mkdir -p "$PACKAGE_DIR/apps/wechat_ai_customer_service/scripts"
mkdir -p "$PACKAGE_DIR/apps/wechat_ai_customer_service/tests"
mkdir -p "$PACKAGE_DIR/runtime/add_friend_live"

copy_file() {
  local src="$1"
  local dst="$2"
  mkdir -p "$(dirname "$PACKAGE_DIR/$dst")"
  cp "$ROOT/$src" "$PACKAGE_DIR/$dst"
}

copy_file "README.md" "README.md"
copy_file "pyproject.toml" "pyproject.toml"
copy_file "apps/__init__.py" "apps/__init__.py"
copy_file "apps/wechat_ai_customer_service/__init__.py" "apps/wechat_ai_customer_service/__init__.py"
copy_file "apps/wechat_ai_customer_service/README.md" "apps/wechat_ai_customer_service/README.md"
copy_file "apps/wechat_ai_customer_service/docs/add_friend_rpa_pr_readiness_20260616.md" "apps/wechat_ai_customer_service/docs/add_friend_rpa_pr_readiness_20260616.md"
copy_file "apps/wechat_ai_customer_service/requirements-add-friend.txt" "apps/wechat_ai_customer_service/requirements-add-friend.txt"
copy_file "apps/wechat_ai_customer_service/wechat_message_envelope.py" "apps/wechat_ai_customer_service/wechat_message_envelope.py"
copy_file "apps/wechat_ai_customer_service/wechat_message_normalizer.py" "apps/wechat_ai_customer_service/wechat_message_normalizer.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_actions.py" "apps/wechat_ai_customer_service/adapters/add_friend_actions.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_artifacts.py" "apps/wechat_ai_customer_service/adapters/add_friend_artifacts.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_contract.py" "apps/wechat_ai_customer_service/adapters/add_friend_contract.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_diagnostics.py" "apps/wechat_ai_customer_service/adapters/add_friend_diagnostics.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_flow.py" "apps/wechat_ai_customer_service/adapters/add_friend_flow.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_flow_context.py" "apps/wechat_ai_customer_service/adapters/add_friend_flow_context.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_flow_events.py" "apps/wechat_ai_customer_service/adapters/add_friend_flow_events.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_locator.py" "apps/wechat_ai_customer_service/adapters/add_friend_locator.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_ocr.py" "apps/wechat_ai_customer_service/adapters/add_friend_ocr.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_pacing.py" "apps/wechat_ai_customer_service/adapters/add_friend_pacing.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_payloads.py" "apps/wechat_ai_customer_service/adapters/add_friend_payloads.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_result_mapping.py" "apps/wechat_ai_customer_service/adapters/add_friend_result_mapping.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_routes.py" "apps/wechat_ai_customer_service/adapters/add_friend_routes.py"
copy_file "apps/wechat_ai_customer_service/adapters/add_friend_screenshot.py" "apps/wechat_ai_customer_service/adapters/add_friend_screenshot.py"
copy_file "apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py" "apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py"
copy_file "apps/wechat_ai_customer_service/adapters/wechat_connector.py" "apps/wechat_ai_customer_service/adapters/wechat_connector.py"
copy_file "apps/wechat_ai_customer_service/scripts/run_wechat_add_friend_entry_click_plan.ps1" "apps/wechat_ai_customer_service/scripts/run_wechat_add_friend_entry_click_plan.ps1"
copy_file "apps/wechat_ai_customer_service/scripts/check_wechat_add_friend_entry_click_latest.ps1" "apps/wechat_ai_customer_service/scripts/check_wechat_add_friend_entry_click_latest.ps1"
copy_file "apps/wechat_ai_customer_service/tests/run_add_friend_package_smoke.py" "apps/wechat_ai_customer_service/tests/run_add_friend_package_smoke.py"

find "$PACKAGE_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
rm -f "$OUT"
mkdir -p "$(dirname "$OUT")"
(cd "$WORKDIR" && zip -qr "$OUT" "omniauto-add-friend-rpa")

echo "$OUT"
