"""Pure window action planners for the Windows WeChat Win32/OCR adapter."""

from __future__ import annotations

from typing import Any

from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import bounded_int


def _geometry_int(geometry: dict[str, Any], key: str) -> int:
    try:
        return int(geometry.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def plan_normalize_wechat_window(
    before: dict[str, Any],
    *,
    enabled: bool,
    requested_width: Any,
    requested_height: Any,
    requested_left: Any,
    requested_top: Any,
    enforce_recommended: bool,
    fixed_origin: bool,
    screen_width: int,
    screen_height: int,
    screen_metrics_available: bool,
    default_width: int,
    default_height: int,
    min_width: int,
    min_height: int,
    max_width: int,
    max_height: int,
) -> dict[str, Any]:
    before_geometry = dict(before or {})
    if not enabled:
        return {"ok": True, "enabled": False, "applied": False, "before": before_geometry}

    target_width = bounded_int(requested_width, default=default_width, minimum=min_width, maximum=max_width)
    target_height = bounded_int(requested_height, default=default_height, minimum=min_height, maximum=max_height)
    requested_target = {"width": target_width, "height": target_height}
    recommended_floor_applied = False
    if enforce_recommended:
        if target_width < default_width:
            target_width = default_width
            recommended_floor_applied = True
        if target_height < default_height:
            target_height = default_height
            recommended_floor_applied = True
    effective_target = {"width": target_width, "height": target_height}

    safe_screen_width = int(screen_width or 0) if screen_metrics_available else 0
    safe_screen_height = int(screen_height or 0) if screen_metrics_available else 0
    if screen_metrics_available:
        safe_width = min(target_width, max(640, safe_screen_width - 12))
        safe_height = min(target_height, max(640, safe_screen_height - 58))
        if fixed_origin:
            left = bounded_int(
                requested_left,
                default=0,
                minimum=0,
                maximum=max(0, safe_screen_width - safe_width),
            )
            top = bounded_int(
                requested_top,
                default=0,
                minimum=0,
                maximum=max(0, safe_screen_height - safe_height),
            )
        else:
            left = min(max(0, _geometry_int(before_geometry, "left")), max(0, safe_screen_width - safe_width))
            top = min(max(0, _geometry_int(before_geometry, "top")), max(0, safe_screen_height - safe_height))
    else:
        safe_width = target_width
        safe_height = target_height
        if fixed_origin:
            left = bounded_int(requested_left, default=0, minimum=0, maximum=max_width)
            top = bounded_int(requested_top, default=0, minimum=0, maximum=max_height)
        else:
            left = max(0, _geometry_int(before_geometry, "left"))
            top = max(0, _geometry_int(before_geometry, "top"))

    width_diff = abs(_geometry_int(before_geometry, "width") - safe_width)
    height_diff = abs(_geometry_int(before_geometry, "height") - safe_height)
    left_diff = abs(_geometry_int(before_geometry, "left") - left)
    top_diff = abs(_geometry_int(before_geometry, "top") - top)
    already_near_target = width_diff <= 6 and height_diff <= 6 and left_diff <= 4 and top_diff <= 4

    return {
        "ok": True,
        "enabled": True,
        "move": not already_near_target,
        "before": before_geometry,
        "target": effective_target,
        "requested_target": requested_target,
        "enforce_recommended": bool(enforce_recommended),
        "recommended_floor_applied": bool(recommended_floor_applied),
        "fixed_origin": bool(fixed_origin),
        "screen": {"width": safe_screen_width, "height": safe_screen_height},
        "left": int(left),
        "top": int(top),
        "width": int(safe_width),
        "height": int(safe_height),
        "reason": "needs_normalize" if not already_near_target else "already_near_target",
    }
