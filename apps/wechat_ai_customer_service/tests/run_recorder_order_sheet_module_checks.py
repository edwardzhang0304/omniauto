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
from apps.wechat_ai_customer_service.admin_backend.services import recorder_export_run_service as export_run_module  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.background_handlers import handle_recorder_export_run_execute  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.recorder_export_run_service import RecorderExportRunService  # noqa: E402
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
    original_call_deepseek_json = export_run_module.call_deepseek_json
    export_run_module.call_deepseek_json = lambda _prompt: {}
    try:
        client = TestClient(create_app())
        headers = {"X-Tenant-ID": TEST_TENANT}
        seed_order_messages(client, headers)
        bind_module(client, headers)
        run_id = create_run(client, headers)
        execute_run(run_id)
        validate_export(client, headers, run_id)
        validate_date_range_runs(client, headers)
        validate_name_context_inference_rules()
        validate_brand_single_use_rules()
    finally:
        export_run_module.call_deepseek_json = original_call_deepseek_json


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
            {
                "id": "order_sheet_004",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "赵宁-王老师\nHEPES缓冲液 订 99元",
                "time": "2025-03-04 08:05:00",
            },
            {
                "id": "order_sheet_005",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "是的2瓶",
                "time": "2025-03-04 08:05:20",
            },
            {
                "id": "order_sheet_006",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "李华-张老师\n赠品：一次性手套 1盒",
                "time": "2025-03-04 08:06:00",
            },
            {
                "id": "order_sheet_007",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "源叶\n羟基酪醇    S25716-1g   384*0.9=345.6元\n秦皮乙素    S31424-1g   100*0.9=90元\n赵伟睿老师",
                "time": "2025-03-04 08:10:00",
            },
            {
                "id": "order_sheet_008",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "白鲨 50ml离心管 订2包 60元",
                "time": "2025-03-04 08:12:00",
            },
            {
                "id": "order_sheet_009",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "杰乐普 透析袋MD77 8000-14000 1米 238元",
                "time": "2025-03-04 08:15:00",
            },
            {
                "id": "order_sheet_010",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "周梦老师",
                "time": "2025-03-04 08:20:00",
            },
            {
                "id": "order_sheet_011",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "白鲨 15ml离心管 2包 66元",
                "time": "2025-03-04 08:22:00",
            },
            {
                "id": "order_sheet_012",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "@记录员 韩梅老师 请记录 枪头 1盒 20元",
                "time": "2025-03-04 08:23:00",
            },
            {
                "id": "order_sheet_013",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "PBS缓冲液 1瓶 30元",
                "time": "2025-03-04 08:24:00",
            },
            {
                "id": "order_sheet_014",
                "type": "text",
                "sender": "罗永志 企点",
                "content": "葡萄糖 1瓶 10元",
                "time": "2025-03-04 08:28:10",
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
    }
    return create_run_with_payload(client, headers, payload)


def create_run_with_payload(client: TestClient, headers: dict[str, str], payload: dict[str, Any]) -> str:
    response = client.post("/api/recorder/exports/runs", headers=headers, json=payload)
    assert_equal(response.status_code, 200, "create run status")
    item = response.json().get("item", {})
    run_id = str(item.get("run_id") or "")
    assert_true(run_id.startswith("recorder_export_run_"), "run id generated")
    assert_equal(str(item.get("module_key") or ""), "order_sheet_lab_v1", "resolved module should be order_sheet_lab_v1")
    return run_id


def execute_run(run_id: str) -> None:
    queue = WorkQueueService(tenant_id=TEST_TENANT)
    target_job = None
    for _ in range(20):
        claimed = queue.claim(queue="recorder_exports", worker_id="order-sheet-test", limit=50, lock_seconds=120)
        target_job = next((job for job in claimed if str((job.get("payload") or {}).get("run_id") or "") == run_id), None)
        if target_job is not None:
            break
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
    assert_equal(str(item.get("stage") or ""), "completed", "run stage should be completed")
    stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    assert_true(int(stats.get("export_row_count", 0) or 0) >= 2, "export row count should be >= 2")
    assert_true(int(stats.get("llm_calls", 0) or 0) >= 0, "llm call stats should exist")
    progress = item.get("progress") if isinstance(item.get("progress"), dict) else {}
    assert_true(float(progress.get("percent", 0) or 0) >= 1.0, "completed run progress should reach 100%")
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
    hep_es_rows = []
    gift_rows = []
    yuanye_rows = []
    baisha_rows = []
    jielepu_rows = []
    context_name_rows = []
    late_rows = []
    mention_rows = []
    top_confidence_fill_type = ""
    has_colored_row = False
    for row_index in range(2, sheet.max_row + 1):
        product_name = str(sheet.cell(row=row_index, column=8).value or "")
        quantity = str(sheet.cell(row=row_index, column=9).value or "")
        brand = str(sheet.cell(row=row_index, column=12).value or "")
        name = str(sheet.cell(row=row_index, column=3).value or "")
        remark = str(sheet.cell(row=row_index, column=17).value or "")
        fill_type = str(sheet.cell(row=row_index, column=8).fill.fill_type or "")
        if "HEPES" in product_name.upper():
            hep_es_rows.append((product_name, quantity))
        if "手套" in product_name:
            gift_rows.append(product_name)
        if "羟基酪醇" in product_name or "秦皮乙素" in product_name:
            yuanye_rows.append((product_name, brand))
        if "离心管" in product_name and ("白鲨" in product_name or brand == "白鲨"):
            baisha_rows.append((product_name, brand))
        if "透析袋" in product_name and ("杰乐普" in product_name or brand == "杰乐普"):
            jielepu_rows.append((product_name, brand))
        if "15ml离心管" in product_name or "PBS缓冲液" in product_name:
            context_name_rows.append((product_name, name, remark))
        if "葡萄糖" in product_name:
            late_rows.append((product_name, name, remark))
        if "枪头" in product_name:
            mention_rows.append((product_name, name, remark))
        if "甲醛测试盒" in product_name:
            top_confidence_fill_type = fill_type
        if fill_type == "solid":
            has_colored_row = True
    assert_true(any(item[1] in {"2", "2.0"} for item in hep_es_rows), f"follow-up confirmation should补全数量: {hep_es_rows}")
    assert_true(bool(gift_rows), "gift item should remain in exported sheet")
    assert_true(len(yuanye_rows) >= 2, f"yuanye multi-product should split into 2 rows: {yuanye_rows}")
    assert_true(
        all(item[1] in {"源叶", "羟基酪醇", "秦皮乙素", ""} for item in yuanye_rows),
        f"yuanye rows should keep stable split and structured brand-like signal: {yuanye_rows}",
    )
    assert_true(any("白鲨" in item[0] and item[1] == "白鲨" for item in baisha_rows), f"baisha row should carry brand and keep brand in product name: {baisha_rows}")
    assert_true(any("杰乐普" in item[0] and item[1] == "杰乐普" for item in jielepu_rows), f"jielepu row should carry brand and keep brand in product name: {jielepu_rows}")
    assert_true(
        all(item[1] == "周梦" and "姓名来自近3句上下文" in item[2] for item in context_name_rows),
        f"context fallback should infer 周梦 with remark note: {context_name_rows}",
    )
    assert_true(
        all(item[1] != "韩梅" for item in mention_rows),
        f"@ mention name should not be used as buyer evidence: {mention_rows}",
    )
    assert_true(
        all(not item[1] for item in late_rows),
        f"rows out of 5-minute window should not inherit context name: {late_rows}",
    )
    assert_true(has_colored_row, "sheet should contain confidence-colored rows")
    if top_confidence_fill_type:
        assert_true(top_confidence_fill_type in {"", "none"}, f"high-confidence rows should not be colored: {top_confidence_fill_type!r}")
    cost_price = sheet.cell(row=2, column=13).value
    total_cost = sheet.cell(row=2, column=15).value
    assert_true(cost_price in ("", None), "cost price should be empty in V1")
    assert_true(total_cost in ("", None), "total cost should be empty in V1")

    # Deterministic confidence-band color checks.
    svc = RecorderExportRunService(tenant_id=TEST_TENANT)
    assert_true(svc._confidence_fill_for_row({"confidence": 0.96}) is None, ">=0.95 should have no row color")
    assert_true(str((svc._confidence_fill_for_row({"confidence": 0.85}) or {}).fill_type) == "solid", "green band should be solid fill")
    assert_true(str((svc._confidence_fill_for_row({"confidence": 0.70}) or {}).fill_type) == "solid", "yellow band should be solid fill")
    assert_true(str((svc._confidence_fill_for_row({"confidence": 0.40}) or {}).fill_type) == "solid", "red band should be solid fill")


def validate_date_range_runs(client: TestClient, headers: dict[str, str]) -> None:
    day_run = create_run_with_payload(
        client,
        headers,
        {
            "target_names": ["企点售后群"],
            "limit": 10000,
            "date_from": "2025-03-03",
            "date_to": "2025-03-03",
            "quick_range": "day",
            "module_key": "order_sheet_lab_v1",
        },
    )
    execute_run(day_run)
    day_item = fetch_run_item(client, headers, day_run)
    day_dates = read_export_dates(Path(str((day_item.get("artifacts") or {}).get("xlsx_path") or "")))
    assert_true(day_dates == {"2025-03-03"}, f"day export should only contain target day: {day_dates}")

    week_run = create_run_with_payload(
        client,
        headers,
        {
            "target_names": ["企点售后群"],
            "limit": 10000,
            "start_time": "2025-03-03 00:00:00",
            "end_time": "2025-03-09 23:59:59",
            "quick_range": "week",
            "module_key": "order_sheet_lab_v1",
        },
    )
    execute_run(week_run)
    week_item = fetch_run_item(client, headers, week_run)
    week_dates = read_export_dates(Path(str((week_item.get("artifacts") or {}).get("xlsx_path") or "")))
    assert_true({"2025-03-03", "2025-03-04"}.issubset(week_dates), f"week export should include both seeded days: {week_dates}")


def validate_name_context_inference_rules() -> None:
    svc = RecorderExportRunService(tenant_id=TEST_TENANT)
    messages = [
        {"content": "王磊老师", "message_time": "2025-03-10 10:00:00"},
        {"content": "@记录员 李娜老师 请处理", "message_time": "2025-03-10 10:01:00"},
        {"content": "枪头 2盒 30元", "message_time": "2025-03-10 10:03:00"},
        {"content": "PBS 1瓶 20元", "message_time": "2025-03-10 10:07:30"},
    ]
    name, owner, ok = svc._infer_name_owner_from_recent_messages(
        ordered_messages=messages,
        message_index=3,
        max_messages=3,
        max_minutes=5,
    )
    assert_true(ok, "context inference should find candidate name")
    assert_equal(name, "王磊", "context inference should prefer teacher suffix name")
    assert_equal(owner, "王磊", "owner should fallback to name from context")
    no_name, no_owner, no_ok = svc._infer_name_owner_from_recent_messages(
        ordered_messages=messages,
        message_index=4,
        max_messages=3,
        max_minutes=5,
    )
    assert_true(not no_ok and not no_name and not no_owner, "context inference should fail when outside 5-minute window")
    base_row = svc._empty_order_row()
    base_row.update({"product_name": "枪头", "quantity": "2", "unit": "盒", "sale_price": "30", "confidence": 0.9, "needs_review": False})
    adjusted = svc._apply_name_context_fallback_to_row(
        base_row,
        ordered_messages=messages,
        message_index=3,
        max_messages=3,
        max_minutes=5,
        confidence_penalty=0.06,
    )
    assert_equal(str(adjusted.get("name") or ""), "王磊", "fallback row should fill name from context")
    assert_true(float(adjusted.get("confidence") or 0) < 0.9, "context fallback should reduce confidence")
    assert_true("姓名来自近3句上下文" in str(adjusted.get("remark") or ""), "fallback row should include traceable remark")


def validate_brand_single_use_rules() -> None:
    svc = RecorderExportRunService(tenant_id=TEST_TENANT)
    rows = [
        {"product_name": "羟基酪醇", "remark": "羟基酪醇 订1个 100元", "brand": ""},
        {"product_name": "秦皮乙素", "remark": "秦皮乙素 订1个 90元", "brand": ""},
        {"product_name": "50ml离心管", "remark": "50ml离心管 订1包 20元", "brand": ""},
    ]
    source_text = "\n".join(
        [
            "源叶",
            "羟基酪醇 订1个 100元",
            "秦皮乙素 订1个 90元",
            "白鲨 50ml离心管 订1包 20元",
        ]
    )
    out = svc._apply_brand_context_to_rows(rows, source_text=source_text)
    assert_equal(str(out[0].get("brand") or ""), "源叶", "first item should consume nearest upstream brand once")
    assert_equal(str(out[1].get("brand") or ""), "源叶", "strong-anchor rows should allow limited consecutive brand inheritance")
    assert_equal(str(out[2].get("brand") or ""), "白鲨", "current-line explicit brand should win")
    assert_true(str(out[0].get("product_name") or "").startswith("源叶 "), "brand should be displayed in product name")
    assert_true(str(out[1].get("product_name") or "").startswith("源叶 "), "inherited brand should be displayed in product name")
    assert_true(str(out[2].get("product_name") or "").startswith("白鲨 "), "brand should be displayed in product name")


def fetch_run_item(client: TestClient, headers: dict[str, str], run_id: str) -> dict[str, Any]:
    response = client.get(f"/api/recorder/exports/runs/{run_id}", headers=headers)
    assert_equal(response.status_code, 200, "run detail status")
    item = response.json().get("item", {})
    assert_equal(item.get("status"), "succeeded", "run status should be succeeded")
    return item


def read_export_dates(workbook_path: Path) -> set[str]:
    assert_true(workbook_path.exists(), f"workbook should exist: {workbook_path}")
    workbook = load_workbook(workbook_path, data_only=True)
    sheet = workbook["Sheet1"]
    values: set[str] = set()
    for row_index in range(2, sheet.max_row + 1):
        value = str(sheet.cell(row=row_index, column=2).value or "").strip()
        if value:
            values.add(value)
    return values


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
