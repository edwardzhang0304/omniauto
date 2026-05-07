"""Fail-closed cloud gate for WeChat customer-service local runtime."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from apps.wechat_ai_customer_service.auth.vps_client import discover_vps_base_url
from apps.wechat_ai_customer_service.knowledge_paths import parse_cloud_time, shared_runtime_cache_valid, shared_runtime_snapshot_path


_PROBE_CACHE: dict[str, Any] = {"base_url": "", "ok": False, "error": "", "expires_at": 0.0}


def cloud_required_enabled() -> bool:
    return str(os.getenv("WECHAT_CLOUD_REQUIRED", "1")).strip().lower() in {"1", "true", "yes", "on"}


def cloud_online_freshness_seconds() -> int:
    try:
        value = int(os.getenv("WECHAT_CLOUD_ONLINE_MAX_AGE_SECONDS", "90"))
    except ValueError:
        value = 90
    return max(10, min(1800, value))


def cloud_probe_timeout_seconds() -> float:
    try:
        value = float(os.getenv("WECHAT_CLOUD_PROBE_TIMEOUT_SECONDS", "1.5"))
    except ValueError:
        value = 1.5
    return max(0.25, min(8.0, value))


def cloud_probe_cache_seconds() -> float:
    try:
        value = float(os.getenv("WECHAT_CLOUD_PROBE_CACHE_SECONDS", "5"))
    except ValueError:
        value = 5.0
    return max(0.0, min(60.0, value))


def cloud_probe_health(base_url: str) -> tuple[bool, str]:
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return False, "cloud_base_url_missing"
    now = time.monotonic()
    ttl = cloud_probe_cache_seconds()
    if (
        _PROBE_CACHE.get("base_url") == base
        and now < float(_PROBE_CACHE.get("expires_at") or 0.0)
    ):
        return bool(_PROBE_CACHE.get("ok")), str(_PROBE_CACHE.get("error") or "")
    request = urllib.request.Request(
        base + "/v1/health",
        headers={"Accept": "application/json"},
        method="GET",
    )
    ok = False
    error = ""
    try:
        with urllib.request.urlopen(request, timeout=cloud_probe_timeout_seconds()) as response:
            status = int(getattr(response, "status", 200))
            ok = 200 <= status < 300
            if not ok:
                error = f"http_status_{status}"
    except urllib.error.HTTPError as exc:
        ok = False
        error = f"http_error_{int(getattr(exc, 'code', 0) or 0)}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        ok = False
        error = str(exc) or "network_error"
    _PROBE_CACHE.update(
        {
            "base_url": base,
            "ok": ok,
            "error": error,
            "expires_at": now + ttl,
        }
    )
    return ok, error


def cloud_gate_status() -> dict[str, Any]:
    base_url = discover_vps_base_url().strip()
    snapshot_path = shared_runtime_snapshot_path()
    snapshot: dict[str, Any] = {}
    if snapshot_path.exists():
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                snapshot = payload
        except (OSError, json.JSONDecodeError):
            snapshot = {}

    source_ok = str(snapshot.get("source") or "") == "cloud_official_shared_library"
    cache_valid = shared_runtime_cache_valid()
    policy_bundle = snapshot.get("policy_bundle") if isinstance(snapshot.get("policy_bundle"), dict) else {}
    merged = policy_bundle.get("merged") if isinstance(policy_bundle.get("merged"), dict) else {}
    policy_ready = isinstance(merged.get("platform_safety_rules"), dict) and isinstance(merged.get("platform_understanding_rules"), dict)
    issued_at = parse_cloud_time(str(snapshot.get("issued_at") or ""))
    max_age = cloud_online_freshness_seconds()
    now = datetime.now(timezone.utc)
    lease_fresh = bool(issued_at and (now - issued_at).total_seconds() <= max_age)
    strict_online = str(os.getenv("WECHAT_CLOUD_STRICT_ONLINE", "1")).strip().lower() in {"1", "true", "yes", "on"}
    probe_ok, probe_error = cloud_probe_health(base_url) if strict_online else (True, "")
    online_ready = (lease_fresh and probe_ok) if strict_online else True
    vps_configured = bool(base_url)

    ok = bool(vps_configured and source_ok and cache_valid and policy_ready and online_ready)
    reason = ""
    if not vps_configured:
        reason = "cloud_base_url_missing"
    elif strict_online and not probe_ok:
        reason = "cloud_server_unreachable"
    elif not source_ok:
        reason = "cloud_snapshot_missing_or_invalid_source"
    elif not cache_valid:
        reason = "cloud_snapshot_lease_expired"
    elif not policy_ready:
        reason = "cloud_policy_bundle_missing"
    elif not online_ready:
        reason = "cloud_snapshot_not_fresh"

    return {
        "ok": ok,
        "required": cloud_required_enabled(),
        "reason": reason,
        "vps_base_url": base_url,
        "snapshot_path": str(snapshot_path),
        "source_ok": source_ok,
        "cache_valid": cache_valid,
        "policy_ready": policy_ready,
        "strict_online": strict_online,
        "online_ready": online_ready,
        "lease_fresh": lease_fresh,
        "probe_ok": probe_ok,
        "probe_error": probe_error,
        "tenant_industry_id": str(snapshot.get("tenant_industry_id") or ""),
        "issued_at": str(snapshot.get("issued_at") or ""),
        "expires_at": str(snapshot.get("expires_at") or ""),
    }


def cloud_gate_error_payload() -> dict[str, Any]:
    status = cloud_gate_status()
    message = "当前客户端未通过云端授权校验。请连接服务端并完成共享行业知识库刷新后再使用。"
    return {
        "ok": False,
        "detail": {
            "code": "cloud_authoritative_access_required",
            "message": message,
            "cloud_gate": status,
        },
        "message": message,
        "cloud_gate": status,
    }
