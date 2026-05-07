"""System status APIs."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from fastapi import APIRouter, Request

from apps.wechat_ai_customer_service.auth.models import Role
from apps.wechat_ai_customer_service.llm_config import (
    load_llm_config,
    resolve_deepseek_base_url,
    save_llm_config,
)
from apps.wechat_ai_customer_service.platform_safety_rules import load_platform_safety_rules, save_platform_safety_rules
from apps.wechat_ai_customer_service.platform_understanding_rules import load_platform_understanding_rules, save_platform_understanding_rules
from ..auth_context import current_auth_context
from ..services.diagnostics_service import DiagnosticsService
from ..services.handoff_store import HandoffStore
from ..services.knowledge_store import KnowledgeStore
from ..services.locks import list_runtime_locks
from ..services.runtime_monitor import RuntimeMonitor
from ..services.version_store import VersionStore
from ..services.work_queue import WorkQueueService


router = APIRouter(prefix="/api/system", tags=["system"])
knowledge = KnowledgeStore()
diagnostics = DiagnosticsService()
versions = VersionStore()
work_queue = WorkQueueService()
handoffs = HandoffStore()
monitor = RuntimeMonitor()


@router.get("/status")
def status() -> dict[str, Any]:
    overview = knowledge.overview()
    runs = diagnostics.list_runs()
    return {
        "ok": True,
        "knowledge": overview,
        "recent_diagnostic": runs[0] if runs else None,
        "versions": {"count": len(versions.list_versions())},
        "work_queue": work_queue.summary(),
        "handoffs": handoffs.summary(),
        "readiness": monitor.readiness(),
        "locks": list_runtime_locks(),
    }


@router.get("/runtime-locks")
def runtime_locks() -> dict[str, Any]:
    return {"ok": True, "items": list_runtime_locks()}


@router.get("/readiness")
def readiness() -> dict[str, Any]:
    report = monitor.readiness()
    return {"ok": report["ok"], "report": report}


@router.get("/platform-safety-rules")
def platform_safety_rules(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    payload = load_platform_safety_rules()
    item = payload.get("item", {})
    editable = context.role == Role.ADMIN and payload.get("readonly") is not True
    return {
        "ok": bool(payload.get("ok")),
        "path": payload.get("path"),
        "source": payload.get("source", "local_file"),
        "error": payload.get("error", ""),
        "readonly": payload.get("readonly") is True,
        "editable": editable,
        "item": item,
    }


@router.put("/platform-safety-rules")
def update_platform_safety_rules(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = current_auth_context(request)
    if context.role != Role.ADMIN:
        return {"ok": False, "detail": "only admin can update platform safety rules"}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
    result = save_platform_safety_rules(item)
    return {
        "ok": bool(result.get("ok")),
        "path": result.get("path"),
        "source": result.get("source", "local_file"),
        "error": result.get("error", ""),
        "readonly": result.get("readonly") is True,
        "item": result.get("item"),
    }


@router.get("/platform-understanding-rules")
def platform_understanding_rules(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    payload = load_platform_understanding_rules()
    item = payload.get("item", {})
    editable = context.role == Role.ADMIN and payload.get("readonly") is not True
    return {
        "ok": bool(payload.get("ok")),
        "path": payload.get("path"),
        "source": payload.get("source", "local_file"),
        "error": payload.get("error", ""),
        "readonly": payload.get("readonly") is True,
        "editable": editable,
        "item": item,
    }


@router.put("/platform-understanding-rules")
def update_platform_understanding_rules(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = current_auth_context(request)
    if context.role != Role.ADMIN:
        return {"ok": False, "detail": "only admin can update platform understanding rules"}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
    result = save_platform_understanding_rules(item)
    return {
        "ok": bool(result.get("ok")),
        "path": result.get("path"),
        "source": result.get("source", "local_file"),
        "error": result.get("error", ""),
        "readonly": result.get("readonly") is True,
        "item": result.get("item"),
    }


@router.post("/heartbeat/{component_id}")
def heartbeat(component_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "ok": True,
        "item": monitor.heartbeat(
            component_id,
            status=str(payload.get("status") or "ok"),
            message=str(payload.get("message") or ""),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        ),
    }


@router.get("/llm-config")
def llm_config(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    config = load_llm_config()
    key = str(config.get("DEEPSEEK_API_KEY") or "")
    return {
        "ok": True,
        "api_key_configured": bool(key),
        "api_key_masked": _mask_key(key),
        "editable": context.role == Role.ADMIN,
    }


@router.put("/llm-config")
def update_llm_config(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = current_auth_context(request)
    if context.role != Role.ADMIN:
        return {"ok": False, "detail": "only admin can update llm config"}
    config = load_llm_config()
    new_key = str(payload.get("deepseek_api_key") or "").strip()
    if new_key:
        config["DEEPSEEK_API_KEY"] = new_key
    else:
        config.pop("DEEPSEEK_API_KEY", None)
    save_llm_config(config)
    return {
        "ok": True,
        "api_key_configured": bool(config.get("DEEPSEEK_API_KEY")),
        "api_key_masked": _mask_key(str(config.get("DEEPSEEK_API_KEY") or "")),
    }


@router.post("/llm-config/test")
def test_llm_config(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    if context.role != Role.ADMIN:
        return {"ok": False, "detail": "only admin can test llm config"}
    config = load_llm_config()
    api_key = str(config.get("DEEPSEEK_API_KEY") or "")
    if not api_key:
        return {"ok": False, "message": "DEEPSEEK_API_KEY 未配置"}
    base_url = resolve_deepseek_base_url()
    try:
        req = urllib.request.Request(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            status = int(getattr(response, "status", 200))
            if 200 <= status < 300:
                return {"ok": True, "message": "连接成功", "base_url": base_url}
            return {"ok": False, "message": f"HTTP {status}", "base_url": base_url}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "message": f"HTTP {exc.code}: {detail}", "base_url": base_url}
    except urllib.error.URLError as exc:
        return {"ok": False, "message": f"连接失败: {exc.reason}", "base_url": base_url}
    except Exception as exc:
        return {"ok": False, "message": f"测试异常: {exc}", "base_url": base_url}


def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]
