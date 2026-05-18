"""Focused checks for knowledge contamination prevention.

These tests lock the intended safety contract:
- customer-service live observations are audit data, not automatic training data;
- self/file-transfer/test messages never create learning batches;
- raw WeChat batches create review-only RAG experiences, not direct RAG chunks;
- RAG retrieval ignores raw WeChat chunks and product-master facts.
"""

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

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.services.raw_message_learning_service import (  # noqa: E402
    RawMessageLearningService,
)
from apps.wechat_ai_customer_service.admin_backend.services.raw_message_store import RawMessageStore  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.knowledge_contamination_guard import text_has_test_marker  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import tenant_context, tenant_root, tenant_runtime_root  # noqa: E402
from apps.wechat_ai_customer_service.workflows.rag_layer import RagService  # noqa: E402
from apps.wechat_ai_customer_service.workflows.rag_experience_store import RagExperienceStore  # noqa: E402


TEST_TENANT = "knowledge_contamination_guard_test"


def main() -> int:
    cleanup()
    results = []
    try:
        with tenant_context(TEST_TENANT):
            for check in CHECKS:
                try:
                    check()
                    results.append({"name": check.__name__, "ok": True})
                except Exception as exc:
                    results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
                    break
    finally:
        cleanup()
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def check_customer_service_file_transfer_never_batches() -> None:
    store = RawMessageStore()
    result = store.upsert_messages(
        {
            "target_name": "文件传输助手",
            "display_name": "文件传输助手",
            "conversation_type": "file_transfer",
            "learning_enabled": True,
            "allow_learning_from_customer_service": True,
        },
        [
            {
                "id": "ft-001",
                "type": "text",
                "sender": "self",
                "content": "我看秦PLUS，每天通勤40公里，三电能保证吗？(LIVEFLOW_20260519_GUARD)",
                "time": "2026-05-19 10:00:00",
            }
        ],
        source_module="customer_service",
        learning_enabled=True,
        batch_reason="customer_service_poll",
    )
    assert_equal(result.get("batch"), None, "file-transfer self-test should not create a learning batch")
    messages = store.list_messages(limit=10)
    assert_true(messages and messages[0].get("learning_enabled") is False, "captured message should be non-learnable")
    assert_equal(messages[0].get("excluded_reason"), "file_transfer_test_channel", "exclusion reason should be explicit")


def check_customer_service_private_defaults_to_record_only() -> None:
    store = RawMessageStore()
    result = store.upsert_messages(
        {
            "target_name": "真实客户A",
            "display_name": "真实客户A",
            "conversation_type": "private",
            "learning_enabled": True,
        },
        [
            {
                "id": "private-001",
                "type": "text",
                "sender": "客户",
                "content": "我想找一台七座车，预算十五万以内。",
                "time": "2026-05-19 10:01:00",
            }
        ],
        source_module="customer_service",
        learning_enabled=True,
        batch_reason="customer_service_poll",
    )
    assert_equal(result.get("batch"), None, "customer service listener should not auto-learn without explicit source opt-in")
    messages = store.list_messages(query="七座车", limit=5)
    assert_true(messages and messages[0].get("learning_enabled") is False, "private service message should be record-only by default")
    assert_equal(messages[0].get("excluded_reason"), "customer_service_live_learning_disabled", "private exclusion reason")


def check_smart_recorder_review_only_learning() -> None:
    store = RawMessageStore()
    result = store.upsert_messages(
        {
            "target_name": "门店真实记录群",
            "display_name": "门店真实记录群",
            "conversation_type": "group",
            "learning_enabled": True,
            "selected_by_user": True,
            "source": {"type": "smart_recorder"},
        },
        [
            {
                "id": "rec-001",
                "type": "text",
                "sender": "销售小王",
                "content": "客户问置换时，先收车型、上牌年份、公里数、城市和车况照片，再说估价需要复核。",
                "time": "2026-05-19 10:02:00",
            }
        ],
        source_module="smart_recorder",
        learning_enabled=True,
        batch_reason="recorder_capture",
    )
    assert_true(result.get("batch"), "trusted smart recorder message should create a batch")
    learned = RawMessageLearningService().process_batch(result["batch"]["batch_id"], use_llm=False)
    assert_true(str(learned.get("rag_experience_id") or "").startswith("rag_exp_"), "learning should create review-only RAG experience")
    status = RagService().status()
    assert_equal(status.get("source_count"), 0, "raw recorder learning should not create direct rag source")
    assert_equal(status.get("chunk_count"), 0, "raw recorder learning should not create direct rag chunk")
    experiences = RagExperienceStore().list(status="all", limit=20)
    assert_true(any(item.get("experience_id") == learned.get("rag_experience_id") for item in experiences), "RAG experience should be stored")


def check_rag_retrieval_filters_raw_and_product_chunks() -> None:
    service = RagService()
    source_dir = tenant_runtime_root(TEST_TENANT) / "guard_sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    direct_chat_dir = tenant_root(TEST_TENANT) / "raw_inbox" / "chats"
    direct_chat_dir.mkdir(parents=True, exist_ok=True)
    raw_path = source_dir / "raw_wechat.txt"
    product_path = source_dir / "product_master.txt"
    safe_path = source_dir / "safe_policy.txt"
    direct_chat_path = direct_chat_dir / "upload_wechat_usedcar_chat_templates_strict.jsonl"
    raw_path.write_text("客户：我看秦PLUS，每天通勤40公里，三电怎么保证？\n客服：[车金AI] 这个得转人工。\n", encoding="utf-8")
    product_path.write_text("商品资料：2022款比亚迪秦PLUS DM-i 55KM，价格8.68万，库存1台。\n", encoding="utf-8")
    safe_path.write_text("置换流程：先收车型、上牌年份、公里数、城市、车况照片，再提示最终估价需复核。\n", encoding="utf-8")
    direct_chat_path.write_text(
        "{\"customer_message\":\"库存表\",\"service_reply\":\"向您推荐{inventory_count}辆好车。\"}\n",
        encoding="utf-8",
    )
    service.ingest_file(raw_path, source_type="wechat_raw_message", category="private", rebuild_index=True)
    service.ingest_file(product_path, source_type="upload", category="products", rebuild_index=True)
    service.ingest_file(safe_path, source_type="policy_doc", category="policies", rebuild_index=True)
    service.ingest_file(direct_chat_path, source_type="upload", category="chats", rebuild_index=True)
    raw_hits = service.search("秦PLUS 每天通勤40公里 三电", limit=5).get("hits", [])
    assert_true(not any(item.get("source_type") == "wechat_raw_message" for item in raw_hits), "raw WeChat chunks should not be retrievable")
    assert_true(not any(item.get("category") == "products" for item in raw_hits), "product-master chunks should not be generic RAG hits")
    direct_chat_hits = service.search("库存表 推荐几辆车", limit=5).get("hits", [])
    assert_true(not any(item.get("category") == "chats" for item in direct_chat_hits), "direct raw_inbox chat templates should not bypass RAG experience review")
    policy_hits = service.search("置换 上牌年份 公里数 车况照片", limit=5).get("hits", [])
    assert_true(any(item.get("category") == "policies" for item in policy_hits), "safe policy RAG chunks should remain retrievable")


def check_embedded_demo_and_debug_markers_are_blocked() -> None:
    assert_true(text_has_test_marker("chejin_policies_DBG_025836.txt"), "embedded DBG marker should be blocked")
    assert_true(text_has_test_marker("演示批次：CHEJIN_DEMO_20260503_203628"), "demo batch marker should be blocked")
    assert_true(text_has_test_marker("测试批次：CHEJIN_20260516_123014"), "test batch marker should be blocked")


def cleanup() -> None:
    data_root = tenant_root(TEST_TENANT)
    runtime = tenant_runtime_root(TEST_TENANT)
    for path in (data_root, runtime):
        if path.exists():
            shutil.rmtree(path)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


CHECKS = [
    check_embedded_demo_and_debug_markers_are_blocked,
    check_customer_service_file_transfer_never_batches,
    check_customer_service_private_defaults_to_record_only,
    check_smart_recorder_review_only_learning,
    check_rag_retrieval_filters_raw_and_product_chunks,
]


if __name__ == "__main__":
    raise SystemExit(main())
