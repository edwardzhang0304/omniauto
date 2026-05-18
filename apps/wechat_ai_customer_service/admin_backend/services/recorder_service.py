"""AI smart recorder orchestration on top of the shared raw message store."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .raw_message_learning_service import RawMessageLearningService
from .raw_message_store import RawMessageStore
from apps.wechat_ai_customer_service.adapters.wechat_connector import WeChatConnector
from apps.wechat_ai_customer_service.knowledge_paths import tenant_runtime_root


DEFAULT_SETTINGS = {
    "enabled": True,
    "private_recording_enabled": True,
    "group_recording_enabled": True,
    "file_transfer_recording_enabled": True,
    "notify_on_collect": False,
    "auto_learn": True,
    "use_llm": True,
    "capture_interval_seconds": 30,
}
RECORDER_DISCOVERY_SOURCE_TYPE = "wechat_session_discovery"


class RecorderService:
    def __init__(self, *, tenant_id: str | None = None) -> None:
        self.raw_store = RawMessageStore(tenant_id=tenant_id)
        self.learning = RawMessageLearningService(tenant_id=tenant_id)
        self.connector = WeChatConnector()

    @property
    def settings_path(self) -> Path:
        return tenant_runtime_root(self.raw_store.tenant_id) / "recorder" / "settings.json"

    def settings(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return dict(DEFAULT_SETTINGS)
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return dict(DEFAULT_SETTINGS)
        return {**DEFAULT_SETTINGS, **(payload if isinstance(payload, dict) else {})}

    def save_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        settings = {**self.settings(), **{key: value for key, value in patch.items() if key in DEFAULT_SETTINGS}}
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.settings_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.settings_path)
        return settings

    def summary(self) -> dict[str, Any]:
        raw = self.raw_store.summary()
        settings = self.settings()
        conversations = self._live_session_conversations(self.raw_store.list_conversations(status="all", limit=500))
        selected_groups = [item for item in conversations if item.get("conversation_type") == "group" and item.get("selected_by_user")]
        selected_private = [item for item in conversations if item.get("conversation_type") == "private" and item.get("selected_by_user")]
        selected_file_transfer = [item for item in conversations if item.get("conversation_type") == "file_transfer" and item.get("selected_by_user")]
        return {
            "settings": settings,
            "status": status_text(settings),
            "raw": raw,
            "selected_group_count": len(selected_groups),
            "selected_private_count": len(selected_private),
            "selected_file_transfer_count": len(selected_file_transfer),
            "selected_conversation_count": len(selected_groups) + len(selected_private) + len(selected_file_transfer),
            "selected_groups": selected_groups,
            "selected_private": selected_private,
            "selected_file_transfer": selected_file_transfer,
        }

    def discover_sessions(self) -> dict[str, Any]:
        # Discovery must reflect the currently logged-in WeChat window in real time,
        # so we force a fresh sidecar attachment instead of daemon cache reuse.
        payload = self.connector.list_sessions(fresh=True)
        sessions = payload.get("sessions", []) if payload.get("ok") else []
        existing_records = self.raw_store.list_conversations(status="all", limit=500)
        existing_by_name = {
            str(item.get("target_name") or "").strip(): item
            for item in existing_records
            if isinstance(item, dict) and str(item.get("target_name") or "").strip()
        }
        discovered_names: set[str] = set()
        items = []
        for session in sessions or []:
            if not isinstance(session, dict):
                continue
            conversation = normalize_session(session)
            target_name = str(conversation.get("target_name") or "").strip()
            if not target_name:
                continue
            discovered_names.add(target_name)
            existing = existing_by_name.get(target_name)
            if existing:
                conversation = {**conversation, **preserved_selection(existing), "status": "active"}
            items.append(self.raw_store.upsert_conversation(conversation))
        archived_items: list[dict[str, Any]] = []
        if payload.get("ok"):
            archived_items = self._archive_missing_discovered_conversations(
                existing_records=existing_records,
                discovered_names=discovered_names,
            )
        return {
            "ok": bool(payload.get("ok")),
            "items": items,
            "archived_items": archived_items,
            "archived_count": len(archived_items),
            "source": payload,
        }

    def ensure_conversation(self, record: dict[str, Any]) -> dict[str, Any]:
        target_name = str(record.get("target_name") or record.get("name") or record.get("display_name") or "").strip()
        if not target_name:
            raise ValueError("target_name is required")
        existing = self.find_conversation_by_name(target_name)
        payload = {**(existing or {}), **record, "target_name": target_name, "display_name": record.get("display_name") or target_name}
        return self.raw_store.upsert_conversation(payload)

    def list_conversations(self, *, conversation_type: str = "", status: str = "all") -> list[dict[str, Any]]:
        conversations = self.raw_store.list_conversations(conversation_type=conversation_type, status=status, limit=500)
        return self._live_session_conversations(conversations)

    def update_conversation(self, conversation_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = next((item for item in self.raw_store.list_conversations(status="all", limit=500) if item.get("conversation_id") == conversation_id), None)
        if not current:
            raise FileNotFoundError(conversation_id)
        updated = {
            **current,
            "selected_by_user": bool(patch.get("selected_by_user", current.get("selected_by_user", False))),
            "conversation_type": normalized_patch_conversation_type(patch.get("conversation_type"), current.get("conversation_type")),
            "target_name": str(patch.get("target_name") or current.get("target_name") or ""),
            "display_name": str(patch.get("display_name") or current.get("display_name") or current.get("target_name") or ""),
            "status": str(patch.get("status") or current.get("status") or "active"),
            "notify_enabled": bool(patch.get("notify_enabled", current.get("notify_enabled", False))),
            "learning_enabled": patch.get("learning_enabled", current.get("learning_enabled", True)) is not False,
            "updated_at": now_iso(),
        }
        return self.raw_store.upsert_conversation(updated)

    def capture_selected_once(self, *, send_notifications: bool = False) -> dict[str, Any]:
        settings = self.settings()
        if settings.get("enabled", True) is False:
            return {
                "ok": True,
                "enabled": False,
                "message": "AI智能记录员总开关已关闭，本轮不采集。",
                "conversation_count": 0,
                "inserted_count": 0,
                "items": [],
            }
        conversations = [
            item
            for item in self.list_conversations(status="active")
            if item.get("selected_by_user") and conversation_enabled_for_capture(item, settings)
        ]
        results = []
        for conversation in conversations:
            result = self.capture_conversation(
                conversation,
                auto_learn=bool(settings.get("auto_learn", True)),
                use_llm=settings.get("use_llm", True) is not False,
                send_notification=bool(send_notifications and (settings.get("notify_on_collect") or conversation.get("notify_enabled"))),
            )
            results.append(result)
        return {
            "ok": True,
            "enabled": True,
            "conversation_count": len(conversations),
            "inserted_count": sum(int(item.get("inserted_count", 0) or 0) for item in results),
            "items": results,
        }

    def capture_conversation(
        self,
        conversation: dict[str, Any],
        *,
        auto_learn: bool,
        use_llm: bool,
        send_notification: bool,
    ) -> dict[str, Any]:
        target_name = str(conversation.get("target_name") or conversation.get("display_name") or "")
        payload = self.connector.get_messages(target_name, exact=conversation.get("exact", True) is not False)
        if not payload.get("ok"):
            return {"ok": False, "conversation_id": conversation.get("conversation_id"), "messages": payload}
        result = self.raw_store.upsert_messages(
            conversation,
            [item for item in payload.get("messages", []) or [] if isinstance(item, dict)],
            source_module="smart_recorder",
            learning_enabled=conversation.get("learning_enabled", True) is not False,
            create_batch=True,
            batch_reason="recorder_capture",
        )
        if auto_learn and result.get("batch"):
            result["learning"] = self.learning.process_batch(str(result["batch"].get("batch_id") or ""), use_llm=use_llm)
        if send_notification and result.get("inserted_count"):
            result["notification"] = self.connector.send_text(
                target_name,
                f"已自动记录 {result['inserted_count']} 条新消息，整理结果会进入后台候选知识待确认。",
                exact=conversation.get("exact", True) is not False,
            )
        return result

    def find_conversation_by_name(self, target_name: str) -> dict[str, Any] | None:
        for item in self.raw_store.list_conversations(status="all", limit=500):
            if str(item.get("target_name") or "") == target_name:
                return item
        return None

    def _archive_missing_discovered_conversations(
        self,
        *,
        existing_records: list[dict[str, Any]],
        discovered_names: set[str],
    ) -> list[dict[str, Any]]:
        archived_items: list[dict[str, Any]] = []
        if not existing_records:
            return archived_items
        snapshot_time = now_iso()
        for existing in existing_records:
            target_name = str(existing.get("target_name") or "").strip()
            if not target_name or target_name in discovered_names:
                continue
            if str(existing.get("status") or "active") != "active":
                continue
            source = existing.get("source") if isinstance(existing.get("source"), dict) else {}
            archived_payload = {
                **existing,
                "status": "ignored",
                "selected_by_user": False,
                "updated_at": snapshot_time,
                "source": {
                    **source,
                    "archived_by_discover": True,
                    "archived_reason": "missing_from_latest_discovery",
                    "archived_at": snapshot_time,
                },
            }
            archived_items.append(self.raw_store.upsert_conversation(archived_payload))
        return archived_items

    def _live_session_conversations(self, conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in conversations:
            if not isinstance(item, dict):
                continue
            source = item.get("source") if isinstance(item.get("source"), dict) else {}
            source_type = str(source.get("type") or "").strip().lower()
            if source_type != RECORDER_DISCOVERY_SOURCE_TYPE:
                continue
            items.append(item)
        return items


def normalize_session(session: dict[str, Any]) -> dict[str, Any]:
    name = str(session.get("name") or session.get("title") or "").strip()
    return {
        "target_name": name,
        "display_name": name,
        "conversation_type": infer_conversation_type(name, session),
        "status": "active",
        "exact": True,
        "selected_by_user": False,
        "learning_enabled": True,
        "notify_enabled": False,
        "source": {"type": RECORDER_DISCOVERY_SOURCE_TYPE},
        "raw_payload": session,
    }


def infer_conversation_type(name: str, session: dict[str, Any]) -> str:
    explicit = str(session.get("conversation_type") or session.get("type") or "").lower()
    if explicit in {"private", "group", "file_transfer", "system"}:
        return explicit
    if name in {"文件传输助手", "File Transfer"}:
        return "file_transfer"
    if re.search(r"(群|群聊|chatroom|room)", name, re.IGNORECASE):
        return "group"
    return "private"


def preserved_selection(existing: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": existing.get("conversation_id"),
        "conversation_type": existing.get("conversation_type") or "unknown",
        "status": existing.get("status") or "active",
        "selected_by_user": bool(existing.get("selected_by_user", False)),
        "learning_enabled": existing.get("learning_enabled", True) is not False,
        "notify_enabled": bool(existing.get("notify_enabled", False)),
    }


def normalized_patch_conversation_type(value: Any, current: Any) -> str:
    text = str(value or current or "unknown").strip().lower()
    if text in {"private", "group", "file_transfer", "system", "unknown"}:
        return text
    return str(current or "unknown")


def conversation_enabled_for_capture(conversation: dict[str, Any], settings: dict[str, Any]) -> bool:
    if settings.get("enabled", True) is False:
        return False
    conversation_type = str(conversation.get("conversation_type") or "unknown")
    if conversation_type == "group":
        return settings.get("group_recording_enabled", True) is not False
    if conversation_type == "file_transfer":
        return settings.get("file_transfer_recording_enabled", True) is not False
    if conversation_type == "private":
        return settings.get("private_recording_enabled", True) is not False
    return False


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def status_text(settings: dict[str, Any]) -> str:
    if settings.get("enabled", True) is False:
        return "已关闭，不会自动采集或整理聊天记录。"
    return "已开启，可按已选择会话自动采集聊天记录。"
