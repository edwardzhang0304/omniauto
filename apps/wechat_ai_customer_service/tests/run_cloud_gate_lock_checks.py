"""Checks for fail-closed cloud gate behavior in local admin backend."""

from __future__ import annotations

import json
import os
import sys
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient


APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(APP_ROOT, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402


def main() -> int:
    old_cloud_required = os.environ.get("WECHAT_CLOUD_REQUIRED")
    old_auth_required = os.environ.get("WECHAT_AUTH_REQUIRED")
    os.environ["WECHAT_CLOUD_REQUIRED"] = "1"
    os.environ["WECHAT_AUTH_REQUIRED"] = "0"
    results: list[dict[str, Any]] = []
    try:
        app = create_app()
        client = TestClient(app)

        with patch("apps.wechat_ai_customer_service.admin_backend.auth_context.cloud_required_enabled", return_value=True), patch(
            "apps.wechat_ai_customer_service.admin_backend.auth_context.cloud_gate_status",
            return_value={
                "ok": False,
                "required": True,
                "reason": "cloud_server_unreachable",
                "strict_online": True,
                "probe_ok": False,
            },
        ):
            locked = client.get("/api/system/status")
            assert_equal(locked.status_code, 423, "cloud gate should lock protected APIs when status is not ok")
            locked_payload = locked.json()
            assert_equal(locked_payload.get("detail", {}).get("code"), "cloud_authoritative_access_required", "cloud gate should return explicit lock code")
            sync_status = client.get("/api/sync/status")
            assert_equal(sync_status.status_code, 200, "sync status endpoint must stay available during cloud lock")

        with patch("apps.wechat_ai_customer_service.admin_backend.auth_context.cloud_required_enabled", return_value=True), patch(
            "apps.wechat_ai_customer_service.admin_backend.auth_context.cloud_gate_status",
            return_value={"ok": True, "required": True, "reason": ""},
        ):
            unlocked = client.get("/api/system/status")
            assert_equal(unlocked.status_code, 200, "cloud gate should unlock once status is ok")

        results.append({"name": "cloud_gate_lock_unlock", "ok": True})
    except Exception as exc:
        results.append({"name": "cloud_gate_lock_unlock", "ok": False, "error": repr(exc)})
    finally:
        if old_cloud_required is None:
            os.environ.pop("WECHAT_CLOUD_REQUIRED", None)
        else:
            os.environ["WECHAT_CLOUD_REQUIRED"] = old_cloud_required
        if old_auth_required is None:
            os.environ.pop("WECHAT_AUTH_REQUIRED", None)
        else:
            os.environ["WECHAT_AUTH_REQUIRED"] = old_auth_required

    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "results": results, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
