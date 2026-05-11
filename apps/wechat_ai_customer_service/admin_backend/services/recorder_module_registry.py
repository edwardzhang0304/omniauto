"""Registry and binding resolution for recorder extract/export modules."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import runtime_app_root


SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


BUILTIN_MODULES = [
    {
        "module_key": "raw_message_log_v1",
        "module_name": "通用原始消息导出V1",
        "module_type": "chat_extract_export",
        "status": "active",
        "version": "1.0.0",
        "config": {
            "description": "Generic baseline export that writes raw messages to a readable workbook.",
            "supports_content_types": ["text", "quote", "image", "system"],
        },
        "builtin": True,
    },
    {
        "module_key": "order_sheet_lab_v1",
        "module_name": "实验仪器订货表V1",
        "module_type": "chat_extract_export",
        "status": "active",
        "version": "1.0.0",
        "config": {
            "description": "Rule-first order extraction with optional LLM supplementation, exports to order-sheet style workbook.",
            "date_output_mode": "MMDD_text",
            "allow_empty_cost_fields": True,
            "llm_enabled": True,
            "llm_max_rows_per_run": 40,
            "supported_content_types": ["text", "quote"],
        },
        "builtin": True,
    },
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_id(value: str) -> str:
    text = SAFE_ID_RE.sub("_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("._-")
    if not text:
        return "id_unknown"
    return text[:120]


class RecorderModuleRegistryService:
    """Manage module registry and account/global bindings."""

    def __init__(self) -> None:
        self.root = runtime_app_root() / "admin" / "recorder_modules"

    @property
    def registry_path(self) -> Path:
        return self.root / "module_registry.json"

    @property
    def bindings_path(self) -> Path:
        return self.root / "module_bindings.json"

    def list_modules(self, *, include_inactive: bool = True) -> list[dict[str, Any]]:
        registry = self._read_json(self.registry_path, default=[])
        modules = [item for item in registry if isinstance(item, dict)]
        modules = self._ensure_builtin_modules(modules)
        if not include_inactive:
            modules = [item for item in modules if str(item.get("status") or "active") == "active"]
        modules.sort(key=lambda item: str(item.get("module_key") or ""))
        return modules

    def upsert_module(self, payload: dict[str, Any]) -> dict[str, Any]:
        module_key = safe_id(str(payload.get("module_key") or payload.get("key") or ""))
        if not module_key:
            raise ValueError("module_key is required")
        current = self.list_modules(include_inactive=True)
        by_key = {str(item.get("module_key") or ""): item for item in current}
        existing = by_key.get(module_key, {})
        record = {
            "module_key": module_key,
            "module_name": str(payload.get("module_name") or payload.get("name") or existing.get("module_name") or module_key),
            "module_type": str(payload.get("module_type") or existing.get("module_type") or "chat_extract_export"),
            "status": str(payload.get("status") or existing.get("status") or "active"),
            "version": str(payload.get("version") or existing.get("version") or "1.0.0"),
            "config": payload.get("config") if isinstance(payload.get("config"), dict) else dict(existing.get("config") or {}),
            "builtin": bool(existing.get("builtin", False)),
            "created_at": str(existing.get("created_at") or now_iso()),
            "updated_at": now_iso(),
        }
        by_key[module_key] = record
        items = sorted(by_key.values(), key=lambda item: str(item.get("module_key") or ""))
        self._write_json(self.registry_path, items)
        return record

    def list_bindings(
        self,
        *,
        scope_type: str = "",
        scope_id: str = "",
        tenant_id: str = "",
        user_id: str = "",
    ) -> list[dict[str, Any]]:
        bindings = [
            item
            for item in self._read_json(self.bindings_path, default=[])
            if isinstance(item, dict) and str(item.get("scope_type") or "") in {"user", "global"}
        ]
        if scope_type:
            bindings = [item for item in bindings if str(item.get("scope_type") or "") == scope_type]
        if scope_id:
            bindings = [item for item in bindings if str(item.get("scope_id") or "") == scope_id]
        if user_id:
            bindings = [item for item in bindings if str(item.get("user_id") or "") == user_id]
        bindings.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return bindings

    def upsert_binding(self, payload: dict[str, Any]) -> dict[str, Any]:
        scope_type = str(payload.get("scope_type") or "").strip().lower()
        if scope_type not in {"user", "global"}:
            raise ValueError("scope_type must be one of user|global")
        scope_id = str(payload.get("scope_id") or "").strip()
        if scope_type == "global":
            scope_id = "*"
        if not scope_id:
            raise ValueError("scope_id is required")
        module_key = str(payload.get("module_key") or "").strip()
        if not module_key:
            raise ValueError("module_key is required")
        module = self.get_module(module_key)
        if not module:
            raise ValueError(f"module not found: {module_key}")
        if str(module.get("status") or "active") != "active":
            raise ValueError(f"module is not active: {module_key}")
        user_id = str(payload.get("user_id") or scope_id if scope_type == "user" else "").strip()
        binding_id = safe_id(str(payload.get("binding_id") or f"{scope_type}_{scope_id}"))
        bindings = [item for item in self._read_json(self.bindings_path, default=[]) if isinstance(item, dict)]
        index = next((idx for idx, item in enumerate(bindings) if str(item.get("binding_id") or "") == binding_id), -1)
        existing = bindings[index] if index >= 0 else {}
        record = {
            "binding_id": binding_id,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "tenant_id": "",
            "user_id": user_id,
            "module_key": module_key,
            "enabled": payload.get("enabled", existing.get("enabled", True)) is not False,
            "created_at": str(existing.get("created_at") or now_iso()),
            "updated_at": now_iso(),
        }
        if index >= 0:
            bindings[index] = record
        else:
            bindings.append(record)
        self._write_json(self.bindings_path, bindings)
        return record

    def delete_binding(self, binding_id: str) -> bool:
        bindings = [item for item in self._read_json(self.bindings_path, default=[]) if isinstance(item, dict)]
        filtered = [item for item in bindings if str(item.get("binding_id") or "") != binding_id]
        if len(filtered) == len(bindings):
            return False
        self._write_json(self.bindings_path, filtered)
        return True

    def get_module(self, module_key: str) -> dict[str, Any] | None:
        for item in self.list_modules(include_inactive=True):
            if str(item.get("module_key") or "") == module_key:
                return item
        return None

    def resolve_module(self, *, tenant_id: str, user_id: str = "", requested_module_key: str = "") -> dict[str, Any]:
        if requested_module_key:
            module = self.get_module(requested_module_key)
            if not module:
                raise ValueError(f"module not found: {requested_module_key}")
            if str(module.get("status") or "active") != "active":
                raise ValueError(f"module is not active: {requested_module_key}")
            return module

        bindings = [item for item in self._read_json(self.bindings_path, default=[]) if isinstance(item, dict)]
        active_bindings = [item for item in bindings if item.get("enabled", True) is not False]

        if user_id:
            user_binding = next(
                (
                    item
                    for item in sorted(active_bindings, key=lambda value: str(value.get("updated_at") or ""), reverse=True)
                    if str(item.get("scope_type") or "") == "user" and str(item.get("scope_id") or "") == user_id
                ),
                None,
            )
            if user_binding:
                module = self.get_module(str(user_binding.get("module_key") or ""))
                if module and str(module.get("status") or "active") == "active":
                    return module

        global_binding = next(
            (
                item
                for item in sorted(active_bindings, key=lambda value: str(value.get("updated_at") or ""), reverse=True)
                if str(item.get("scope_type") or "") == "global"
            ),
            None,
        )
        if global_binding:
            module = self.get_module(str(global_binding.get("module_key") or ""))
            if module and str(module.get("status") or "active") == "active":
                return module

        modules = self.list_modules(include_inactive=False)
        if modules:
            return modules[0]
        raise ValueError("no active recorder modules available")

    def _ensure_builtin_modules(self, modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key = {str(item.get("module_key") or ""): item for item in modules}
        changed = False
        for builtin in BUILTIN_MODULES:
            module_key = str(builtin.get("module_key") or "")
            if module_key not in by_key:
                changed = True
                by_key[module_key] = {
                    **builtin,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                }
            else:
                existing = dict(by_key[module_key])
                if existing.get("builtin") is not True:
                    existing["builtin"] = True
                    existing["updated_at"] = now_iso()
                    by_key[module_key] = existing
                    changed = True
        if changed:
            items = sorted(by_key.values(), key=lambda item: str(item.get("module_key") or ""))
            self._write_json(self.registry_path, items)
            return items
        return sorted(by_key.values(), key=lambda item: str(item.get("module_key") or ""))

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
