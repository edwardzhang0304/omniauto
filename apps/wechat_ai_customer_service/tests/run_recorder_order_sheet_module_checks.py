"""Checks for order_sheet_lab_v1 module extraction and export."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("WECHAT_STORAGE_BACKEND", "file")
os.environ.setdefault("WECHAT_CLOUD_REQUIRED", "0")
os.environ.setdefault("WECHAT_CLOUD_STRICT_ONLINE", "0")

from fastapi.testclient import TestClient
from openpyxl import load_workbook


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.background_handlers import handle_recorder_export_run_execute  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.work_queue import WorkQueueService  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import tenant_context, tenant_runtime_root  # noqa: E402


TEST_TENANT = "recorder_order_sheet_test"
ORDER_HEADERS = [
    None,
    "日期",
    "姓名",
    "责任人（老板）",
    "收货人",
    "校区",
    "订货单位",
    "货品名称",
    "数量",
    "单位",
    "规格",
    "品牌",
    "进价（单价）",
    "售价（单价）",
    "总进价",
    "总售价",
    "备注",
]


def main() -> int:
    try:
        with tenant_context(TEST_TENANT):
            cleanup_runtime()
            run_checks()
        print(json.dumps({"ok": True, "tenant": TEST_TENANT}, ensure_ascii=False, indent=2))
        return 0
    finally:
        with tenant_context(TEST_TENANT):
            cleanup_runtime()


def run_checks() -> None:
    client = TestClient(create_app())
    headers = {"X-Tenant-ID": TEST_TENANT}
    seed_order_messages(client, headers)
    bind_module(client, headers)
    run_id = create_run(client, headers)
    execute_run(run_id)
    validate_export(client, headers, run_id)


def seed_order_messages(client: TestClient, headers: dict[str, str]) -> None:
    payload = {
        "conversation": {
            "target_name": "企点售后群",
            "display_name": "企点售后群",
            "conversation_type": "group",
            "selected_by_user": True,
            "learning_enabled": True,
            "notify_enabled": False,
            "status": "active",
        },
        "messages": [
            {
                "id": "order_sheet_001",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "叶松霖-陈秋平老师\n订：甲醛试剂=甲醛测试盒 2盒 98元",
                "time": "2025-03-03 09:12:10",
            },
            {
                "id": "order_sheet_002",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "王一博-李老师\n代付：水质试纸 3盒 45元",
                "time": "2025-03-03 10:20:33",
            },
            {
                "id": "order_sheet_003",
                "type": "quote",
                "sender": "罗永志 企点",
                "content": "李华-张老师\n订：PH试剂 1盒 120元",
                "time": "2025-03-04 08:00:00",
            },
        ],
        "source_module": "order_sheet_test",
        "auto_learn": False,
    }
    response = client.post("/api/raw-messages/messages", headers=headers, json=payload)
    assert_equal(response.status_code, 200, "seed raw messages status")
    result = response.json()
    assert_true(result.get("ok") is True, "seed raw messages ok")
    assert_true(int(result.get("inserted_count", 0) or 0) >= 2, "seed raw messages inserted")


def bind_module(client: TestClient, headers: dict[str, str]) -> None:
    payload = {
        "binding_id": "order_sheet_local_admin_binding",
        "scope_type": "user",
        "scope_id": "local-admin",
        "user_id": "local-admin",
        "module_key": "order_sheet_lab_v1",
        "enabled": True,
    }
    response = client.post("/api/recorder/module-bindings", headers=headers, json=payload)
    assert_equal(response.status_code, 200, "bind module status")
    assert_true(response.json().get("ok") is True, "bind module ok")


def create_run(client: TestClient, headers: dict[str, str]) -> str:
    payload = {
        "target_names": ["企点售后群"],
        "limit": 500,
        "keywords": ["订"],
    }
    response = client.post("/api/recorder/exports/runs", headers=headers, json=payload)
    assert_equal(response.status_code, 200, "create run status")
    item = response.json().get("item", {})
    run_id = str(item.get("run_id") or "")
    assert_true(run_id.startswith("recorder_export_run_"), "run id generated")
    assert_equal(str(item.get("module_key") or ""), "order_sheet_lab_v1", "resolved module should be order_sheet_lab_v1")
    return run_id


def execute_run(run_id: str) -> None:
    queue = WorkQueueService(tenant_id=TEST_TENANT)
    claimed = queue.claim(queue="recorder_exports", worker_id="order-sheet-test", limit=5, lock_seconds=120)
    target_job = next((job for job in claimed if str((job.get("payload") or {}).get("run_id") or "") == run_id), None)
    assert_true(target_job is not None, "export run job should be claimable")
    payload = target_job.get("payload") if isinstance(target_job.get("payload"), dict) else {}
    result = handle_recorder_export_run_execute(payload)
    if result.get("ok"):
        queue.complete(str(target_job.get("job_id") or ""), result=result)
        return
    queue.fail(str(target_job.get("job_id") or ""), error=str(result.get("error") or "run failed"), retry=False)
    raise AssertionError(f"order sheet export failed: {result}")


def validate_export(client: TestClient, headers: dict[str, str], run_id: str) -> None:
    response = client.get(f"/api/recorder/exports/runs/{run_id}", headers=headers)
    assert_equal(response.status_code, 200, "run detail status")
    item = response.json().get("item", {})
    assert_equal(item.get("status"), "succeeded", "run status should be succeeded")
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    assert_true(int(stats.get("export_row_count", 0) or 0) >= 2, "export row count should be >= 2")
    artifacts = item.get("artifacts") if isinstance(item.get("artifacts"), dict) else {}
    workbook_path = Path(str(artifacts.get("xlsx_path") or ""))
    report_path = Path(str(artifacts.get("report_path") or ""))
    assert_true(workbook_path.exists(), "xlsx exists")
    assert_true(report_path.exists(), "report exists")

    workbook = load_workbook(workbook_path)
    sheet = workbook["Sheet1"]
    headers_row = [sheet.cell(row=1, column=index + 1).value for index in range(len(ORDER_HEADERS))]
    assert_equal(headers_row, ORDER_HEADERS, "order sheet header should match expected template")
    first_date = str(sheet.cell(row=2, column=2).value or "")
    first_name = str(sheet.cell(row=2, column=3).value or "")
    first_product = str(sheet.cell(row=2, column=8).value or "")
    assert_true(first_date in {"2025-03-03", "2025-03-04"}, "date should be YYYY-MM-DD text")
    assert_true(bool(first_name), "name should be extracted")
    assert_true(bool(first_product), "product name should be extracted")
    cost_price = sheet.cell(row=2, column=13).value
    total_cost = sheet.cell(row=2, column=15).value
    assert_true(cost_price in ("", None), "cost price should be empty in V1")
    assert_true(total_cost in ("", None), "total cost should be empty in V1")


def cleanup_runtime() -> None:
    root = tenant_runtime_root(TEST_TENANT)
    if root.exists():
        shutil.rmtree(root)


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
