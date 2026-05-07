"""Checks for runtime start guard in cloud-required mode."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime import CustomerServiceRuntime  # noqa: E402


def main() -> int:
    old_cloud_required = os.environ.get("WECHAT_CLOUD_REQUIRED")
    os.environ["WECHAT_CLOUD_REQUIRED"] = "1"
    results: list[dict[str, Any]] = []
    try:
        results.append(check_runtime_start_requires_snapshot_refresh())
        results.append(check_runtime_start_requires_cloud_gate())
    finally:
        if old_cloud_required is None:
            os.environ.pop("WECHAT_CLOUD_REQUIRED", None)
        else:
            os.environ["WECHAT_CLOUD_REQUIRED"] = old_cloud_required
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "results": results, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def check_runtime_start_requires_snapshot_refresh() -> dict[str, Any]:
    with patch(
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime.cloud_required_enabled",
        return_value=True,
    ), patch(
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime.write_runtime_status",
        return_value={},
    ), patch.object(
        CustomerServiceRuntime,
        "status",
        return_value={"running": False, "state": "stopped", "tenant_id": "default"},
    ), patch(
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime.VpsLocalSyncService",
    ) as sync_cls:
        sync_instance = sync_cls.return_value
        sync_instance.fetch_shared_knowledge_snapshot.return_value = {"ok": False, "error": "network_down"}
        runtime = CustomerServiceRuntime(tenant_id="default")
        result = runtime.start(token="token-example")
        assert_equal(result.get("ok"), False, "runtime start should fail when snapshot refresh fails")
        assert_equal(result.get("detail"), "cloud_snapshot_refresh_failed", "should return refresh-failed detail")
        sync_instance.fetch_shared_knowledge_snapshot.assert_called_once_with(
            token="token-example",
            tenant_id="default",
            force=True,
        )
    return {"name": "check_runtime_start_requires_snapshot_refresh", "ok": True}


def check_runtime_start_requires_cloud_gate() -> dict[str, Any]:
    with patch(
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime.cloud_required_enabled",
        return_value=True,
    ), patch(
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime.cloud_gate_status",
        return_value={"ok": False, "reason": "cloud_server_unreachable"},
    ), patch(
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime.write_runtime_status",
        return_value={},
    ), patch.object(
        CustomerServiceRuntime,
        "status",
        return_value={"running": False, "state": "stopped", "tenant_id": "default"},
    ), patch(
        "apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime.VpsLocalSyncService",
    ) as sync_cls:
        sync_instance = sync_cls.return_value
        sync_instance.fetch_shared_knowledge_snapshot.return_value = {"ok": True, "updated": True}
        runtime = CustomerServiceRuntime(tenant_id="default")
        result = runtime.start(token="token-example")
        assert_equal(result.get("ok"), False, "runtime start should fail when cloud gate is closed")
        assert_equal(result.get("detail"), "cloud_authoritative_access_required", "should return cloud gate detail")
    return {"name": "check_runtime_start_requires_cloud_gate", "ok": True}


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
