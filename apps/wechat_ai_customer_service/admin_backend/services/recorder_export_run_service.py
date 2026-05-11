"""Async recorder export run service with module-based execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from apps.wechat_ai_customer_service.admin_backend.services.raw_message_store import RawMessageStore
from apps.wechat_ai_customer_service.admin_backend.services.recorder_module_registry import RecorderModuleRegistryService
from apps.wechat_ai_customer_service.admin_backend.services.work_queue import WorkQueueService
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root
from apps.wechat_ai_customer_service.workflows.generate_review_candidates import call_deepseek_json


MAX_RUN_RECORDS = 2000
ORDER_HEADERS = [
    "",
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
NAME_OWNER_RE = re.compile(r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,24})[-—](?P<owner>[\u4e00-\u9fa5A-Za-z0-9]{1,24})老师")
ORDER_UNIT_PATTERN = r"盒|箱|袋|瓶|套|个|包|桶|台|件|支|根|片|株|卷|张|箱装|包/盒|公斤|斤"
QTY_UNIT_RE = re.compile(rf"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{ORDER_UNIT_PATTERN})")
QTY_CN_UNIT_RE = re.compile(rf"(?:各)?(?:订|买|代付)?\s*(?P<qty_cn>[一二两俩三四五六七八九十百半])\s*(?P<unit>{ORDER_UNIT_PATTERN})")
PRICE_RE = re.compile(r"(?P<price>\d+(?:\.\d+)?)\s*元")
DATE_RE = re.compile(r"(?P<year>\d{4})[-/](?P<month>\d{1,2})[-/](?P<day>\d{1,2})")
MONTH_DAY_RE = re.compile(r"(?P<month>\d{1,2})月(?P<day>\d{1,2})日")
ORDER_HINT_TERMS = ("订", "代付", "老师", "元", "收货", "发货", "下单")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stable_digest(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


class RecorderExportRunService:
    """Create, execute, track and download recorder export runs."""

    def __init__(self, *, tenant_id: str | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.raw_store = RawMessageStore(tenant_id=self.tenant_id)
        self.modules = RecorderModuleRegistryService()
        self.queue = WorkQueueService(tenant_id=self.tenant_id)

    @property
    def root(self) -> Path:
        return tenant_runtime_root(self.tenant_id) / "recorder" / "exports"

    @property
    def runs_path(self) -> Path:
        return self.root / "runs.json"

    @property
    def files_root(self) -> Path:
        return self.root / "files"

    @property
    def reports_root(self) -> Path:
        return self.root / "reports"

    def list_runs(self, *, status: str = "all", limit: int = 100) -> list[dict[str, Any]]:
        records = [item for item in self._read_json(self.runs_path, default=[]) if isinstance(item, dict)]
        if status and status != "all":
            records = [item for item in records if str(item.get("status") or "") == status]
        records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return records[: max(1, min(int(limit or 100), 500))]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        for item in self.list_runs(status="all", limit=MAX_RUN_RECORDS):
            if str(item.get("run_id") or "") == run_id:
                return item
        return None

    def create_run(
        self,
        payload: dict[str, Any],
        *,
        requested_by_user_id: str,
        requested_by_username: str = "",
        requested_module_key: str = "",
    ) -> dict[str, Any]:
        module = self.modules.resolve_module(
            tenant_id=self.tenant_id,
            user_id=requested_by_user_id,
            requested_module_key=requested_module_key or str(payload.get("module_key") or ""),
        )
        filters = normalize_filters(payload)
        now_text = now_iso()
        run_id = "recorder_export_run_" + stable_digest(
            json.dumps(
                {
                    "tenant_id": self.tenant_id,
                    "module_key": module.get("module_key"),
                    "filters": filters,
                    "requested_by_user_id": requested_by_user_id,
                    "created_at": now_text,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            20,
        )
        run = {
            "run_id": run_id,
            "tenant_id": self.tenant_id,
            "requested_by_user_id": requested_by_user_id,
            "requested_by_username": requested_by_username,
            "module_key": str(module.get("module_key") or ""),
            "module_version": str(module.get("version") or ""),
            "module_name": str(module.get("module_name") or module.get("module_key") or ""),
            "status": "queued",
            "queue_name": "recorder_exports",
            "filters": filters,
            "stats": {
                "input_message_count": 0,
                "export_row_count": 0,
                "needs_review_count": 0,
                "skipped_count": 0,
            },
            "artifacts": {
                "xlsx_path": "",
                "report_path": "",
            },
            "error": "",
            "created_at": now_text,
            "updated_at": now_text,
            "started_at": "",
            "finished_at": "",
        }
        self._upsert_run(run)
        self.queue.enqueue(
            kind="recorder_export_run_execute",
            payload={"tenant_id": self.tenant_id, "run_id": run_id},
            queue="recorder_exports",
            dedupe_key=f"recorder_export_run_execute:{run_id}",
            priority=5,
        )
        return run

    def process_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if not run:
            raise FileNotFoundError(run_id)
        if str(run.get("status") or "") == "succeeded":
            return {"ok": True, "already_done": True, "run": run}

        started_at = now_iso()
        running = {
            **run,
            "status": "running",
            "started_at": started_at,
            "updated_at": started_at,
            "error": "",
        }
        self._upsert_run(running)
        try:
            messages = self._load_messages_for_run(running)
            workbook_result = self._build_workbook(running, messages)
            report_path = self._write_report(running, messages, workbook_result)
            completed = {
                **running,
                "status": "succeeded",
                "stats": {
                    "input_message_count": len(messages),
                    "export_row_count": int(workbook_result.get("export_row_count", 0) or 0),
                    "needs_review_count": int(workbook_result.get("needs_review_count", 0) or 0),
                    "skipped_count": int(workbook_result.get("skipped_count", 0) or 0),
                },
                "artifacts": {
                    "xlsx_path": str(workbook_result.get("xlsx_path") or ""),
                    "report_path": str(report_path),
                },
                "updated_at": now_iso(),
                "finished_at": now_iso(),
            }
            self._upsert_run(completed)
            return {"ok": True, "run": completed}
        except Exception as exc:
            failed = {
                **running,
                "status": "failed",
                "error": repr(exc),
                "updated_at": now_iso(),
                "finished_at": now_iso(),
            }
            self._upsert_run(failed)
            return {"ok": False, "error": repr(exc), "run": failed}

    def ensure_run_job(self, run_id: str) -> dict[str, Any]:
        run_id = str(run_id or "").strip()
        if not run_id:
            raise ValueError("run_id is required")
        run = self.get_run(run_id)
        if not run:
            raise FileNotFoundError(run_id)
        status = str(run.get("status") or "")
        if status not in {"queued", "running"}:
            return {"ok": True, "skipped": True, "reason": f"run_status_{status or 'unknown'}"}
        dedupe_key = f"recorder_export_run_execute:{run_id}"
        existing = self.queue.find_active_dedupe(queue="recorder_exports", dedupe_key=dedupe_key)
        if existing:
            return {"ok": True, "existing_job": existing}
        job = self.queue.enqueue(
            kind="recorder_export_run_execute",
            payload={"tenant_id": self.tenant_id, "run_id": run_id},
            queue="recorder_exports",
            dedupe_key=dedupe_key,
            priority=5,
        )
        return {"ok": True, "job": job, "requeued": True}

    def _load_messages_for_run(self, run: dict[str, Any]) -> list[dict[str, Any]]:
        filters = run.get("filters") if isinstance(run.get("filters"), dict) else {}
        conversation_ids = [str(item) for item in filters.get("conversation_ids", []) if str(item)]
        target_names = [str(item) for item in filters.get("target_names", []) if str(item)]
        if target_names:
            conversations = self.raw_store.list_conversations(status="all", limit=500)
            lookup = {str(item.get("target_name") or ""): str(item.get("conversation_id") or "") for item in conversations}
            for target_name in target_names:
                conv_id = lookup.get(target_name, "")
                if conv_id:
                    conversation_ids.append(conv_id)
        conversation_ids = sorted(set(item for item in conversation_ids if item))
        if not conversation_ids:
            return self.raw_store.list_messages_advanced(
                query=str(filters.get("query") or ""),
                limit=int(filters.get("limit", 10000) or 10000),
                offset=int(filters.get("offset", 0) or 0),
                start_time=str(filters.get("start_time") or ""),
                end_time=str(filters.get("end_time") or ""),
                sender=str(filters.get("sender") or ""),
                content_type=str(filters.get("content_type") or ""),
                conversation_type=str(filters.get("conversation_type") or ""),
                keywords=[str(item) for item in filters.get("keywords", []) if str(item)],
            )
        merged: dict[str, dict[str, Any]] = {}
        for conversation_id in conversation_ids:
            items = self.raw_store.list_messages_advanced(
                conversation_id=conversation_id,
                query=str(filters.get("query") or ""),
                limit=int(filters.get("limit", 10000) or 10000),
                offset=int(filters.get("offset", 0) or 0),
                start_time=str(filters.get("start_time") or ""),
                end_time=str(filters.get("end_time") or ""),
                sender=str(filters.get("sender") or ""),
                content_type=str(filters.get("content_type") or ""),
                conversation_type=str(filters.get("conversation_type") or ""),
                keywords=[str(item) for item in filters.get("keywords", []) if str(item)],
            )
            for item in items:
                message_id = str(item.get("raw_message_id") or item.get("dedupe_key") or "")
                if message_id:
                    merged[message_id] = item
        return sorted(merged.values(), key=lambda item: str(item.get("observed_at") or ""), reverse=True)

    def _build_workbook(self, run: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
        module_key = str(run.get("module_key") or "")
        if module_key == "raw_message_log_v1":
            path = self._build_raw_message_workbook(run, messages)
            return {
                "xlsx_path": str(path),
                "export_row_count": len(messages),
                "needs_review_count": 0,
                "skipped_count": 0,
                "rows_preview": [],
            }
        if module_key == "order_sheet_lab_v1":
            extracted = self._extract_order_rows(run, messages)
            path = self._build_order_sheet_workbook(run, extracted)
            needs_review = sum(1 for item in extracted if item.get("needs_review"))
            return {
                "xlsx_path": str(path),
                "export_row_count": len(extracted),
                "needs_review_count": needs_review,
                "skipped_count": max(0, len(messages) - len(extracted)),
                "rows_preview": extracted[:100],
            }
        raise ValueError(f"unsupported module for current generic runtime: {module_key}")

    def _build_raw_message_workbook(self, run: dict[str, Any], messages: list[dict[str, Any]]) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "记录导出"
        headers = ["会话ID", "会话类型", "发送人", "消息类型", "消息时间", "消息内容", "原始消息ID"]
        header_fill = PatternFill("solid", fgColor="EAF2F8")
        for column, header in enumerate(headers, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.font = Font(bold=True)
            cell.fill = header_fill
        for row_index, item in enumerate(messages, start=2):
            values = [
                item.get("conversation_id") or "",
                item.get("conversation_type") or "",
                item.get("sender") or item.get("sender_role") or "",
                item.get("content_type") or "",
                item.get("message_time") or item.get("observed_at") or "",
                item.get("content") or "",
                item.get("raw_message_id") or "",
            ]
            for column, value in enumerate(values, start=1):
                sheet.cell(row=row_index, column=column, value=value)
        widths = [24, 14, 16, 12, 20, 80, 28]
        for idx, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=idx).column_letter].width = width

        self.files_root.mkdir(parents=True, exist_ok=True)
        output_path = self.files_root / f"{run['run_id']}.xlsx"
        workbook.save(output_path)
        return output_path

    def _build_order_sheet_workbook(self, run: dict[str, Any], rows: list[dict[str, Any]]) -> Path:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Sheet1"
        header_fill = PatternFill("solid", fgColor="EAF2F8")
        for column, header in enumerate(ORDER_HEADERS, start=1):
            cell = sheet.cell(row=1, column=column, value=header)
            cell.font = Font(bold=True)
            cell.fill = header_fill

        for row_index, item in enumerate(rows, start=2):
            values = [
                "",
                item.get("date") or "",
                item.get("name") or "",
                item.get("owner") or "",
                item.get("receiver") or "",
                item.get("campus") or "",
                item.get("order_unit") or "",
                item.get("product_name") or "",
                item.get("quantity") or "",
                item.get("unit") or "",
                item.get("spec") or "",
                item.get("brand") or "",
                item.get("cost_price") or "",
                item.get("sale_price") or "",
                item.get("total_cost") or "",
                item.get("total_sale") or "",
                item.get("remark") or "",
            ]
            for column, value in enumerate(values, start=1):
                sheet.cell(row=row_index, column=column, value=value)
        widths = [8, 10, 14, 16, 14, 12, 12, 32, 10, 10, 18, 12, 12, 12, 12, 12, 28]
        for idx, width in enumerate(widths, start=1):
            sheet.column_dimensions[sheet.cell(row=1, column=idx).column_letter].width = width

        meta = workbook.create_sheet(title="抽取报告")
        meta_rows = [
            ("模块", str(run.get("module_key") or "")),
            ("版本", str(run.get("module_version") or "")),
            ("导出时间", now_iso()),
            ("记录行数", len(rows)),
            ("需复核行数", sum(1 for item in rows if item.get("needs_review"))),
        ]
        for index, (key, value) in enumerate(meta_rows, start=1):
            meta.cell(row=index, column=1, value=key).font = Font(bold=True)
            meta.cell(row=index, column=2, value=value)
        meta.cell(row=8, column=1, value="样例（最多100行）").font = Font(bold=True)
        report_headers = ["日期", "姓名", "责任人", "货品", "数量", "单位", "售价", "总售价", "置信度", "需复核", "证据消息ID"]
        for column, header in enumerate(report_headers, start=1):
            cell = meta.cell(row=9, column=column, value=header)
            cell.font = Font(bold=True)
            cell.fill = header_fill
        for row_index, item in enumerate(rows[:100], start=10):
            values = [
                item.get("date") or "",
                item.get("name") or "",
                item.get("owner") or "",
                item.get("product_name") or "",
                item.get("quantity") or "",
                item.get("unit") or "",
                item.get("sale_price") or "",
                item.get("total_sale") or "",
                float(item.get("confidence") or 0),
                "是" if item.get("needs_review") else "",
                ",".join(str(x) for x in item.get("evidence_message_ids", []) if str(x)),
            ]
            for column, value in enumerate(values, start=1):
                meta.cell(row=row_index, column=column, value=value)
        for idx, width in enumerate([10, 14, 14, 24, 10, 10, 10, 10, 10, 10, 36], start=1):
            meta.column_dimensions[meta.cell(row=9, column=idx).column_letter].width = width

        self.files_root.mkdir(parents=True, exist_ok=True)
        output_path = self.files_root / f"{run['run_id']}.xlsx"
        workbook.save(output_path)
        return output_path

    def _write_report(self, run: dict[str, Any], messages: list[dict[str, Any]], workbook_result: dict[str, Any]) -> Path:
        self.reports_root.mkdir(parents=True, exist_ok=True)
        report = {
            "run_id": run.get("run_id"),
            "tenant_id": run.get("tenant_id"),
            "module_key": run.get("module_key"),
            "module_version": run.get("module_version"),
            "message_count": len(messages),
            "artifact": str(workbook_result.get("xlsx_path") or ""),
            "stats": {
                "export_row_count": int(workbook_result.get("export_row_count", 0) or 0),
                "needs_review_count": int(workbook_result.get("needs_review_count", 0) or 0),
                "skipped_count": int(workbook_result.get("skipped_count", 0) or 0),
            },
            "generated_at": now_iso(),
            "filters": run.get("filters") if isinstance(run.get("filters"), dict) else {},
            "rows_preview": workbook_result.get("rows_preview", []),
        }
        report_path = self.reports_root / f"{run['run_id']}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report_path

    def _extract_order_rows(self, run: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        module = self.modules.get_module(str(run.get("module_key") or "")) or {}
        config = module.get("config") if isinstance(module.get("config"), dict) else {}
        llm_enabled = bool(config.get("llm_enabled", True))
        llm_budget = max(0, int(config.get("llm_max_rows_per_run", 40) or 40))
        content_types = {str(item).lower() for item in (config.get("supported_content_types") or ["text", "quote"])}
        rows: list[dict[str, Any]] = []
        llm_used = 0
        for message in sorted(messages, key=lambda item: str(item.get("message_time") or item.get("observed_at") or "")):
            content_type = str(message.get("content_type") or "text").lower()
            if content_types and content_type not in content_types:
                continue
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            if not self._looks_like_order_message(content):
                continue
            extracted = self._rule_extract_rows_from_message(message)
            if not extracted and llm_enabled and llm_used < llm_budget:
                llm_row = self._llm_extract_single_row(message)
                if llm_row:
                    extracted = [llm_row]
                    llm_used += 1
            for row in extracted:
                if llm_enabled and row.get("needs_review") and llm_used < llm_budget:
                    improved = self._llm_supplement_row(message, row)
                    if improved:
                        row = improved
                        llm_used += 1
                rows.append(self._finalize_order_row(row, message))
        return rows

    def _rule_extract_rows_from_message(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        content = str(message.get("content") or "")
        if not content.strip():
            return []
        name, owner = self._extract_name_owner(content)
        date_code = self._extract_date_code(str(message.get("message_time") or message.get("observed_at") or ""))
        lines = [line.strip() for line in re.split(r"[\r\n]+", content) if line.strip()]
        if not lines:
            lines = [content.strip()]
        rows: list[dict[str, Any]] = []
        for line in lines:
            if not self._line_has_order_signal(line):
                continue
            parsed = self._parse_line_item(line)
            if not parsed:
                continue
            if not str(parsed.get("product_name") or "").strip() and not str(parsed.get("sale_price") or "").strip() and not str(parsed.get("total_sale") or "").strip():
                continue
            row = self._empty_order_row()
            row["date"] = date_code
            row["name"] = name
            row["owner"] = owner
            row["receiver"] = parsed.get("receiver") or ""
            row["order_unit"] = parsed.get("order_unit") or parsed.get("unit") or ""
            row["product_name"] = parsed.get("product_name") or ""
            row["quantity"] = parsed.get("quantity") or ""
            row["unit"] = parsed.get("unit") or ""
            row["sale_price"] = parsed.get("sale_price") or ""
            row["total_sale"] = parsed.get("total_sale") or ""
            row["remark"] = parsed.get("remark") or ""
            row["confidence"] = self._estimate_confidence(row)
            row["needs_review"] = bool(row["confidence"] < 0.75 or not row["product_name"] or not row["quantity"])
            row["evidence_message_ids"] = [str(message.get("raw_message_id") or "")]
            rows.append(row)
        if rows:
            return rows
        multiline = self._parse_multiline_message_item(content)
        if multiline:
            row = self._empty_order_row()
            row["date"] = date_code
            row["name"] = name
            row["owner"] = owner
            row["product_name"] = multiline.get("product_name") or ""
            row["quantity"] = multiline.get("quantity") or ""
            row["unit"] = multiline.get("unit") or ""
            row["sale_price"] = multiline.get("sale_price") or ""
            row["total_sale"] = multiline.get("total_sale") or ""
            row["order_unit"] = multiline.get("order_unit") or multiline.get("unit") or ""
            row["remark"] = multiline.get("remark") or ""
            row["confidence"] = self._estimate_confidence(row)
            row["needs_review"] = bool(row["confidence"] < 0.75 or not row["product_name"])
            row["evidence_message_ids"] = [str(message.get("raw_message_id") or "")]
            return [row]
        fallback = self._parse_line_item(content)
        if not fallback:
            return []
        row = self._empty_order_row()
        row["date"] = date_code
        row["name"] = name
        row["owner"] = owner
        row["product_name"] = fallback.get("product_name") or ""
        row["quantity"] = fallback.get("quantity") or ""
        row["unit"] = fallback.get("unit") or ""
        row["sale_price"] = fallback.get("sale_price") or ""
        row["total_sale"] = fallback.get("total_sale") or ""
        row["remark"] = fallback.get("remark") or ""
        row["confidence"] = self._estimate_confidence(row)
        row["needs_review"] = bool(row["confidence"] < 0.75 or not row["product_name"])
        row["evidence_message_ids"] = [str(message.get("raw_message_id") or "")]
        return [row]

    def _parse_line_item(self, line: str) -> dict[str, Any]:
        text = self._normalize_order_text(str(line or ""))
        if not text:
            return {}
        quantity, unit = self._extract_quantity_unit(text)
        price_match = PRICE_RE.search(text)
        sale_price = price_match.group("price") if price_match else ""
        total_sale = ""
        formula_total = self._extract_formula_total(text)
        if formula_total:
            total_sale = self._format_number(self._to_number(formula_total))
        receiver = ""
        if "收货" in text and "老师" in text:
            receiver_match = re.search(r"收货[人者]?[：:\s]*(?P<receiver>[\u4e00-\u9fa5A-Za-z0-9]{1,20})老师", text)
            if receiver_match:
                receiver = str(receiver_match.group("receiver") or "")
        product_name = self._extract_product_name(text)
        qty_value = self._to_number(quantity)
        sale_value = self._to_number(sale_price)
        total_value = self._to_number(total_sale)
        if qty_value > 0 and total_value > 0:
            sale_price = self._format_number(total_value / qty_value)
        elif qty_value > 0 and sale_value > 0:
            total_sale = self._format_number(qty_value * sale_value)
        elif total_value > 0:
            sale_price = self._format_number(total_value)
        if not quantity and not unit and (total_value > 0 or sale_value > 0):
            if re.search(rf"(订|买|各订)\s*[一1]\s*({ORDER_UNIT_PATTERN})", text):
                quantity = "1"
                one_unit = re.search(rf"(订|买|各订)\s*[一1]\s*(?P<unit>{ORDER_UNIT_PATTERN})", text)
                unit = str(one_unit.group("unit") or "") if one_unit else ""
        return {
            "receiver": receiver,
            "order_unit": unit,
            "product_name": product_name,
            "quantity": self._format_number(self._to_number(quantity)) if quantity else "",
            "unit": unit,
            "sale_price": self._format_number(self._to_number(sale_price)) if sale_price else "",
            "total_sale": total_sale,
            "remark": text,
        }

    def _extract_product_name(self, text: str) -> str:
        candidate = self._normalize_order_text(text)
        if not candidate:
            return ""
        if "[引用" in candidate and "]" in candidate:
            quoted = candidate.split("[引用", 1)[1].rsplit("]", 1)[0]
            if "：" in quoted:
                candidate = quoted.split("：", 1)[1]
            elif ":" in quoted:
                candidate = quoted.split(":", 1)[1]
            else:
                candidate = quoted
            candidate = self._normalize_order_text(candidate)

        marker_match = re.search(r"(各订|订|下单|代付|买)\s*[一二两俩三四五六七八九十百半\d]", candidate)
        cut_index = marker_match.start() if marker_match else len(candidate)
        formula_match = re.search(r"(?:\d+(?:\.\d+)?(?:\s*[*xX×/]\s*\d+(?:\.\d+)?)+)\s*=\s*\d+(?:\.\d+)?\s*元?", candidate)
        if formula_match:
            cut_index = min(cut_index, formula_match.start())
        total_price_match = re.search(r"\d+(?:\.\d+)?\s*元", candidate)
        if total_price_match:
            cut_index = min(cut_index, total_price_match.start())
        candidate = candidate[:cut_index].strip() if cut_index > 0 else candidate

        candidate = re.sub(rf"\b\d+(?:\.\d+)?\s*(?:{ORDER_UNIT_PATTERN})\b", "", candidate)
        candidate = re.sub(rf"\b[一二两俩三四五六七八九十百半]\s*(?:{ORDER_UNIT_PATTERN})\b", "", candidate)
        candidate = re.sub(r"(已订|（已订）|\(已订\)|（已）|\(已\)|已送|代付|下单)", "", candidate)
        candidate = re.sub(r"(老师|收货[人者]?)", "", candidate)
        candidate = re.sub(r"货号[：:]\s*[A-Za-z0-9_-]+", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+", " ", candidate).strip(" ,，。;；:-[]")

        if re.match(r"^[（(].+[）)]$", candidate):
            return ""
        if re.match(r"^[\u4e00-\u9fa5]{2,4}\]?$", candidate) and "老师" in str(text or ""):
            return ""
        return candidate

    @staticmethod
    def _normalize_order_text(text: str) -> str:
        normalized = str(text or "").replace("\xa0", " ")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @staticmethod
    def _cn_to_number(value: str) -> float:
        text = str(value or "").strip()
        mapping = {
            "半": 0.5,
            "一": 1.0,
            "二": 2.0,
            "两": 2.0,
            "俩": 2.0,
            "三": 3.0,
            "四": 4.0,
            "五": 5.0,
            "六": 6.0,
            "七": 7.0,
            "八": 8.0,
            "九": 9.0,
            "十": 10.0,
        }
        if text in mapping:
            return mapping[text]
        if text == "十二":
            return 12.0
        if text == "十一":
            return 11.0
        if text == "十三":
            return 13.0
        return 0.0

    def _extract_quantity_unit(self, text: str) -> tuple[str, str]:
        qty_match = QTY_UNIT_RE.search(text)
        if qty_match:
            return str(qty_match.group("qty") or ""), str(qty_match.group("unit") or "")
        qty_cn = QTY_CN_UNIT_RE.search(text)
        if qty_cn:
            cn_value = self._cn_to_number(str(qty_cn.group("qty_cn") or ""))
            if cn_value > 0:
                return self._format_number(cn_value), str(qty_cn.group("unit") or "")
        return "", ""

    @staticmethod
    def _extract_formula_total(text: str) -> str:
        formula = re.search(r"(?:\d+(?:\.\d+)?(?:\s*[*xX×/]\s*\d+(?:\.\d+)?)+)\s*=\s*(?P<total>\d+(?:\.\d+)?)\s*元?", text)
        if formula:
            return str(formula.group("total") or "")
        simple = re.search(r"(?P<a>\d+(?:\.\d+)?)\s*[*xX×]\s*(?P<b>\d+(?:\.\d+)?)\s*=\s*(?P<c>\d+(?:\.\d+)?)\s*元?", text)
        if simple:
            return str(simple.group("c") or "")
        divide = re.search(r"(?P<a>\d+(?:\.\d+)?)\s*/\s*(?P<b>\d+(?:\.\d+)?)\s*=\s*(?P<c>\d+(?:\.\d+)?)\s*元?", text)
        if divide:
            return str(divide.group("c") or "")
        return ""

    def _parse_multiline_message_item(self, content: str) -> dict[str, Any]:
        lines = [self._normalize_order_text(line) for line in re.split(r"[\r\n]+", str(content or "")) if self._normalize_order_text(line)]
        if len(lines) < 2:
            return {}
        signal_indexes = [idx for idx, line in enumerate(lines) if self._line_has_order_signal(line)]
        if not signal_indexes:
            return {}
        best: dict[str, Any] = {}
        best_score = -1.0
        for idx in signal_indexes:
            composed = self._compose_multiline_order_text(lines, idx)
            if not composed:
                continue
            parsed = self._parse_line_item(composed)
            if not parsed:
                continue
            score = 0.0
            if parsed.get("product_name"):
                score += 1.0
            if parsed.get("quantity"):
                score += 0.6
            if parsed.get("sale_price") or parsed.get("total_sale"):
                score += 0.4
            if score > best_score:
                best_score = score
                best = parsed
        return best

    def _compose_multiline_order_text(self, lines: list[str], index: int) -> str:
        selected: list[str] = []
        for prev in range(index - 1, -1, -1):
            line = lines[prev]
            if self._looks_like_non_product_line(line):
                continue
            if line in selected:
                continue
            selected.append(line)
            break
        selected.append(lines[index])
        for nxt in range(index + 1, min(len(lines), index + 3)):
            line = lines[nxt]
            if self._extract_formula_total(line) or PRICE_RE.search(line):
                selected.append(line)
                break
        return self._normalize_order_text(" ".join(selected))

    @staticmethod
    def _looks_like_non_product_line(line: str) -> bool:
        text = str(line or "").strip()
        if not text:
            return True
        if re.match(r"^[\u4e00-\u9fa5A-Za-z0-9]{2,24}老师$", text):
            return True
        if re.match(r"^(货号|批号|型号)[：:]", text):
            return True
        if re.match(r"^[A-Za-z0-9._-]{2,20}$", text):
            return True
        if re.match(r"^\d+(?:\.\d+)?\s*元$", text):
            return True
        return False

    def _extract_name_owner(self, text: str) -> tuple[str, str]:
        match = NAME_OWNER_RE.search(text)
        if not match:
            single = re.search(r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,24})老师", text)
            if single:
                name = str(single.group("name") or "")
                return name, name
            return "", ""
        return str(match.group("name") or ""), str(match.group("owner") or "")

    def _extract_date_code(self, value: str) -> str:
        text = str(value or "")
        match = DATE_RE.search(text)
        if match:
            year = int(match.group("year") or 0)
            month = int(match.group("month") or 0)
            day = int(match.group("day") or 0)
            if year and month and day:
                return f"{year:04d}-{month:02d}-{day:02d}"
        match = MONTH_DAY_RE.search(text)
        if match:
            month = int(match.group("month") or 0)
            day = int(match.group("day") or 0)
            if month and day:
                inferred_year = datetime.now().year
                year_match = re.search(r"(?P<year>20\d{2})", text)
                if year_match:
                    inferred_year = int(year_match.group("year") or inferred_year)
                return f"{inferred_year:04d}-{month:02d}-{day:02d}"
        return ""

    def _looks_like_order_message(self, text: str) -> bool:
        normalized = str(text or "")
        if len(normalized) < 3:
            return False
        if QTY_UNIT_RE.search(normalized) and PRICE_RE.search(normalized):
            return True
        hits = sum(1 for term in ORDER_HINT_TERMS if term in normalized)
        return hits >= 2

    def _line_has_order_signal(self, line: str) -> bool:
        normalized = self._normalize_order_text(line)
        qty, unit = self._extract_quantity_unit(normalized)
        if qty and unit:
            return True
        if PRICE_RE.search(normalized) and any(term in normalized for term in ("订", "代付", "下单", "买", "各订")):
            return True
        if re.search(r"(各订|订|下单|买)\s*[一二两俩三四五六七八九十百半\d]", normalized):
            return True
        if self._extract_formula_total(normalized) and any(term in normalized for term in ("订", "代付", "各订", "发货")):
            return True
        return False

    def _empty_order_row(self) -> dict[str, Any]:
        return {
            "date": "",
            "name": "",
            "owner": "",
            "receiver": "",
            "campus": "",
            "order_unit": "",
            "product_name": "",
            "quantity": "",
            "unit": "",
            "spec": "",
            "brand": "",
            "cost_price": "",
            "sale_price": "",
            "total_cost": "",
            "total_sale": "",
            "remark": "",
            "confidence": 0.0,
            "needs_review": True,
            "evidence_message_ids": [],
        }

    def _estimate_confidence(self, row: dict[str, Any]) -> float:
        confidence = 0.35
        if row.get("product_name"):
            confidence += 0.2
        if row.get("quantity"):
            confidence += 0.15
        if row.get("unit"):
            confidence += 0.1
        if row.get("sale_price"):
            confidence += 0.1
        if row.get("name"):
            confidence += 0.05
        if row.get("owner"):
            confidence += 0.05
        return max(0.0, min(confidence, 0.95))

    def _finalize_order_row(self, row: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
        output = {**self._empty_order_row(), **row}
        output["confidence"] = self._coerce_confidence(output.get("confidence"))
        if not output.get("date"):
            output["date"] = self._extract_date_code(str(message.get("message_time") or message.get("observed_at") or ""))
        if output.get("quantity") and output.get("sale_price") and not output.get("total_sale"):
            total = self._to_number(str(output.get("quantity") or "")) * self._to_number(str(output.get("sale_price") or ""))
            if total:
                output["total_sale"] = self._format_number(total)
        output["needs_review"] = bool(
            output.get("needs_review")
            or float(output.get("confidence") or 0) < 0.75
            or not output.get("product_name")
            or not output.get("quantity")
        )
        ids = [str(item) for item in output.get("evidence_message_ids", []) if str(item)]
        if not ids:
            raw_message_id = str(message.get("raw_message_id") or "")
            if raw_message_id:
                ids = [raw_message_id]
        output["evidence_message_ids"] = ids
        return output

    def _llm_extract_single_row(self, message: dict[str, Any]) -> dict[str, Any] | None:
        content = str(message.get("content") or "").strip()
        if not content:
            return None
        prompt = {
            "task": "从微信订货聊天中提取一行结构化订货数据。只允许依据source_text，不允许虚构。",
            "source_text": content,
            "required_schema": {
                "date": "MMDD 文本，可为空",
                "name": "姓名，可为空",
                "owner": "责任人，可为空",
                "receiver": "收货人，可为空",
                "campus": "校区，可为空",
                "order_unit": "订货单位，可为空",
                "product_name": "货品名称，尽量提取",
                "quantity": "数量，可为空",
                "unit": "单位，可为空",
                "spec": "规格，可为空",
                "brand": "品牌，可为空",
                "cost_price": "进价单价，允许空",
                "sale_price": "售价单价，可为空",
                "total_cost": "总进价，允许空",
                "total_sale": "总售价，可为空",
                "remark": "备注，可为空",
                "confidence": "0-1",
            },
            "response_contract": {
                "row": "object",
                "needs_review": "bool",
                "reason": "string",
            },
        }
        payload = call_deepseek_json(prompt)
        row = payload.get("row") if isinstance(payload.get("row"), dict) else {}
        if not row:
            return None
        result = self._empty_order_row()
        for key in result.keys():
            if key in row and key not in {"needs_review", "evidence_message_ids"}:
                result[key] = row.get(key)
        result["confidence"] = max(self._coerce_confidence(result.get("confidence")), self._coerce_confidence(row.get("confidence")))
        result["needs_review"] = bool(payload.get("needs_review", True))
        result["remark"] = str(result.get("remark") or payload.get("reason") or content[:120])
        result["evidence_message_ids"] = [str(message.get("raw_message_id") or "")]
        return self._finalize_order_row(result, message)

    def _llm_supplement_row(self, message: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
        content = str(message.get("content") or "").strip()
        if not content:
            return None
        missing_fields = [
            key
            for key in ("name", "owner", "receiver", "order_unit", "product_name", "quantity", "unit", "sale_price", "total_sale", "spec", "brand")
            if not str(row.get(key) or "").strip()
        ]
        if not missing_fields:
            return None
        prompt = {
            "task": "请基于 source_text 和 rule_row，补全缺失字段。禁止覆盖已有非空字段，禁止虚构。",
            "source_text": content,
            "rule_row": row,
            "missing_fields": missing_fields,
            "response_contract": {
                "fill": {"field": "value"},
                "confidence": "0-1",
                "reason": "string",
            },
        }
        payload = call_deepseek_json(prompt)
        fill = payload.get("fill") if isinstance(payload.get("fill"), dict) else {}
        if not fill:
            return None
        updated = dict(row)
        for key, value in fill.items():
            if key in updated and not str(updated.get(key) or "").strip():
                updated[key] = value
        llm_conf = self._coerce_confidence(payload.get("confidence"))
        updated["confidence"] = max(float(updated.get("confidence") or 0), min(0.95, llm_conf * 0.9))
        reason = str(payload.get("reason") or "")
        if reason:
            updated["remark"] = str(updated.get("remark") or "")
            if reason not in updated["remark"]:
                updated["remark"] = (updated["remark"] + f" | LLM补充: {reason}").strip(" |")
        return self._finalize_order_row(updated, message)

    @staticmethod
    def _to_number(value: str) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            try:
                cleaned = re.sub(r"[^\d.]+", "", text)
                return float(cleaned) if cleaned else 0.0
            except ValueError:
                return 0.0

    @staticmethod
    def _format_number(value: float) -> str:
        if abs(value - int(value)) < 1e-9:
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _coerce_confidence(value: Any) -> float:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return max(0.0, min(float(value), 1.0))
        if isinstance(value, dict):
            for key in ("confidence", "score", "value"):
                if key in value:
                    return RecorderExportRunService._coerce_confidence(value.get(key))
            return 0.0
        text = str(value or "").strip()
        if not text:
            return 0.0
        try:
            parsed = float(text)
        except ValueError:
            return 0.0
        return max(0.0, min(parsed, 1.0))

    def _upsert_run(self, run: dict[str, Any]) -> dict[str, Any]:
        records = [item for item in self._read_json(self.runs_path, default=[]) if isinstance(item, dict)]
        by_id = {str(item.get("run_id") or ""): item for item in records}
        existing = by_id.get(str(run.get("run_id") or ""), {})
        merged = {**existing, **run}
        merged["updated_at"] = str(run.get("updated_at") or now_iso())
        by_id[str(merged.get("run_id") or "")] = merged
        saved = sorted(by_id.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)[:MAX_RUN_RECORDS]
        self._write_json(self.runs_path, saved)
        return merged

    def _read_json(self, path: Path, *, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        return payload

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)


def normalize_filters(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_ids": [str(item) for item in payload.get("conversation_ids", []) if str(item)],
        "target_names": [str(item) for item in payload.get("target_names", []) if str(item)],
        "query": str(payload.get("query") or ""),
        "start_time": str(payload.get("start_time") or ""),
        "end_time": str(payload.get("end_time") or ""),
        "sender": str(payload.get("sender") or ""),
        "content_type": str(payload.get("content_type") or ""),
        "conversation_type": str(payload.get("conversation_type") or ""),
        "keywords": [str(item) for item in payload.get("keywords", []) if str(item)],
        "offset": max(0, int(payload.get("offset", 0) or 0)),
        "limit": max(1, min(int(payload.get("limit", 10000) or 10000), 10000)),
    }
