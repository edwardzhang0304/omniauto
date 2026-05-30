"""Checks that cloud-authoritative mode does not fall back to implicit local admin."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402
from apps.wechat_ai_customer_service.auth import AuthService  # noqa: E402


def main() -> int:
    old_cloud_required = os.environ.get("WECHAT_CLOUD_REQUIRED")
    old_auth_required = os.environ.get("WECHAT_AUTH_REQUIRED")
    results: list[dict[str, Any]] = []
    try:
        results.append(check_cloud_required_defaults_to_login_required())
        results.append(check_explicit_dev_auth_bypass_still_requires_opt_in())
        results.append(check_runtime_start_requires_login_in_cloud_mode())
    finally:
        restore_env("WECHAT_CLOUD_REQUIRED", old_cloud_required)
        restore_env("WECHAT_AUTH_REQUIRED", old_auth_required)

    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "results": results, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def check_cloud_required_defaults_to_login_required() -> dict[str, Any]:
    os.environ["WECHAT_CLOUD_REQUIRED"] = "1"
    os.environ.pop("WECHAT_AUTH_REQUIRED", None)
    service = AuthService()
    assert_equal(service.settings.required, True, "cloud-required mode should require login by default")
    assert_equal(service.resolve_context(), None, "cloud-required mode must not issue implicit admin without login")
    return {"name": "check_cloud_required_defaults_to_login_required", "ok": True}


def check_explicit_dev_auth_bypass_still_requires_opt_in() -> dict[str, Any]:
    os.environ["WECHAT_CLOUD_REQUIRED"] = "1"
    os.environ["WECHAT_AUTH_REQUIRED"] = "0"
    service = AuthService()
    assert_equal(service.settings.required, False, "explicit WECHAT_AUTH_REQUIRED=0 should remain an opt-in dev bypass")
    context = service.resolve_context()
    assert_true(context is not None and not context.authenticated, "explicit dev bypass may still use implicit local admin")
    return {"name": "check_explicit_dev_auth_bypass_still_requires_opt_in", "ok": True}


def check_runtime_start_requires_login_in_cloud_mode() -> dict[str, Any]:
    os.environ["WECHAT_CLOUD_REQUIRED"] = "1"
    os.environ.pop("WECHAT_AUTH_REQUIRED", None)
    client = TestClient(create_app())
    response = client.post("/api/customer-service/runtime/start", json={})
    assert_equal(response.status_code, 401, "runtime start should require a logged-in local client in cloud mode")
    payload = response.json()
    assert_equal(payload.get("detail"), "authentication required", "runtime start should fail with authentication required")
    return {"name": "check_runtime_start_requires_login_in_cloud_mode", "ok": True}


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
