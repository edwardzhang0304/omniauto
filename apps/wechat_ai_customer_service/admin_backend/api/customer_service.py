"""Customer-service workbench APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from ..services.customer_service_settings import CustomerServiceSettings
from ..services.customer_service_runtime import CustomerServiceRuntime
from ..services.session_monitor import SessionMonitor


router = APIRouter(prefix="/api/customer-service", tags=["customer-service"])


@router.get("/settings")
def get_settings(tenant_id: str | None = Query(default=None)) -> dict[str, Any]:
    return {"ok": True, "item": CustomerServiceSettings(tenant_id=tenant_id).summary()}


@router.put("/settings")
def save_settings(payload: dict[str, Any], tenant_id: str | None = Query(default=None)) -> dict[str, Any]:
    service = CustomerServiceSettings(tenant_id=tenant_id)
    settings = service.save(payload or {})
    return {"ok": True, "item": service.summary() | {"settings": settings}}


@router.get("/runtime/status")
def runtime_status(tenant_id: str | None = Query(default=None)) -> dict[str, Any]:
    return {"ok": True, "item": CustomerServiceRuntime(tenant_id=tenant_id).status()}


@router.post("/runtime/start")
def start_runtime(request: Request, tenant_id: str | None = Query(default=None)) -> dict[str, Any]:
    token = str(request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    return CustomerServiceRuntime(tenant_id=tenant_id).start(token=token)


@router.post("/runtime/stop")
def stop_runtime(tenant_id: str | None = Query(default=None)) -> dict[str, Any]:
    return CustomerServiceRuntime(tenant_id=tenant_id).stop()


@router.get("/sessions")
def list_sessions(tenant_id: str | None = Query(default=None)) -> dict[str, Any]:
    monitor = SessionMonitor(tenant_id=tenant_id)
    return {"ok": True, "sessions": monitor.all_sessions()}
