"""Adaptive layout model for Windows add_friend RPA."""

from __future__ import annotations

from typing import Any, Callable

from apps.wechat_ai_customer_service.adapters.add_friend_locator import make_locator_result, normalize_bounds, normalize_point
from apps.wechat_ai_customer_service.adapters.add_friend_ocr import compact_ocr_text


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def point_in_bounds(x: int, y: int, bounds: list[int]) -> bool:
    left, top, right, bottom = [int(value) for value in normalize_bounds(bounds)]
    return left <= int(x) <= right and top <= int(y) <= bottom


def clamp_point_to_bounds(x: int, y: int, bounds: list[int]) -> tuple[int, int]:
    left, top, right, bottom = [int(value) for value in normalize_bounds(bounds)]
    return (
        bounded_int(x, default=x, minimum=left, maximum=right),
        bounded_int(y, default=y, minimum=top, maximum=bottom),
    )


def item_center(item: dict[str, Any]) -> tuple[int, int]:
    if item.get("center_x") is not None and item.get("center_y") is not None:
        return int(float(item.get("center_x") or 0)), int(float(item.get("center_y") or 0))
    left = int(float(item.get("left") or 0))
    top = int(float(item.get("top") or 0))
    right = int(float(item.get("right") or left))
    bottom = int(float(item.get("bottom") or top))
    return int((left + right) / 2), int((top + bottom) / 2)


def center_of_bounds(bounds: list[int]) -> tuple[int, int]:
    left, top, right, bottom = normalize_bounds(bounds)
    return int((left + right) / 2), int((top + bottom) / 2)


def item_bounds(item: dict[str, Any]) -> list[int]:
    center_x, center_y = item_center(item)
    return normalize_bounds(
        [
            int(float(item.get("left") or center_x)),
            int(float(item.get("top") or center_y)),
            int(float(item.get("right") or center_x)),
            int(float(item.get("bottom") or center_y)),
        ]
    )


def item_snapshot(item: dict[str, Any] | None, image_size: tuple[int, int]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    center_x, center_y = item_center(item)
    return {
        "text": str(item.get("text") or ""),
        "confidence": float(item.get("confidence") or 0.0),
        "bounds": item_bounds(item),
        "center": [center_x, center_y],
        "image_size": [int(image_size[0]), int(image_size[1])],
    }


def default_session_split_x(width: int) -> int:
    if width <= 560:
        return width
    return max(318, min(390, int(width * 0.36)))


def default_search_box_point(geometry: dict[str, Any]) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    return max(98, min(128, int(width * 0.112))), 70


def region_for_point(
    x: int,
    y: int,
    image_size: tuple[int, int],
    *,
    split_x_fn: Callable[[int], int] = default_session_split_x,
) -> str:
    width, height = int(image_size[0]), int(image_size[1])
    split_x = split_x_fn(width)
    nav_right = max(64, min(92, int(width * 0.075)))
    search_bottom = max(112, min(148, int(height * 0.16)))
    if int(x) <= nav_right:
        return "left_nav"
    if int(x) < split_x:
        if int(y) <= search_bottom:
            return "sidebar_search"
        return "session_list"
    if int(y) <= max(96, int(height * 0.12)):
        return "main_header"
    return "main_content"


def plus_entry_safe_bounds(
    image_size: tuple[int, int],
    *,
    split_x_fn: Callable[[int], int] = default_session_split_x,
) -> list[int]:
    width, height = int(image_size[0]), int(image_size[1])
    split_x = split_x_fn(width)
    top = max(36, min(56, int(height * 0.06)))
    bottom = max(top + 36, min(118, int(height * 0.15)))
    left = max(238, min(split_x - 90, int(width * 0.24)))
    right = min(split_x - 18, max(left + 42, int(width * 0.34)))
    return normalize_bounds([left, top, right, bottom])


def find_sidebar_search_anchor_item(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    *,
    split_x_fn: Callable[[int], int] = default_session_split_x,
) -> dict[str, Any] | None:
    width, height = int(image_size[0]), int(image_size[1])
    split_x = split_x_fn(width)
    search_region = [max(72, int(width * 0.07)), 38, max(180, split_x - 48), max(98, int(height * 0.13))]
    candidates: list[dict[str, Any]] = []
    for item in ocr_items or []:
        text = compact_ocr_text(item.get("text"))
        if not text or "搜索" not in text:
            continue
        center_x, center_y = item_center(item)
        if not point_in_bounds(center_x, center_y, search_region):
            continue
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (float(item.get("confidence") or 0.0), -abs(item_center(item)[1] - 70)))


def windows_1080p_reference_plus_point(
    geometry: dict[str, Any],
    *,
    split_x_fn: Callable[[int], int] = default_session_split_x,
    search_box_point_fn: Callable[[dict[str, Any]], tuple[int, int]] = default_search_box_point,
) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    split_x = split_x_fn(width)
    _search_x, search_y = search_box_point_fn(geometry)
    plus_x = bounded_int(split_x - 16, default=354, minimum=max(230, split_x - 48), maximum=max(260, split_x - 8))
    plus_y = bounded_int(search_y, default=70, minimum=48, maximum=130)
    return plus_x, plus_y


def windows_plus_point(
    geometry: dict[str, Any],
    *,
    split_x_fn: Callable[[int], int] = default_session_split_x,
    search_box_point_fn: Callable[[dict[str, Any]], tuple[int, int]] = default_search_box_point,
) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    split_x = split_x_fn(width)
    search_x, search_y = search_box_point_fn(geometry)
    plus_x_hint = search_x + max(170, min(198, int(width * 0.18)))
    plus_x = bounded_int(plus_x_hint, default=302, minimum=max(250, search_x + 145), maximum=min(split_x - 36, search_x + 210))
    plus_y = bounded_int(search_y, default=70, minimum=48, maximum=130)
    return plus_x, plus_y


def plus_entry_target(
    geometry: dict[str, Any],
    image_size: tuple[int, int],
    ocr_items: list[dict[str, Any]] | None = None,
    *,
    route_kind: str = "windows",
    split_x_fn: Callable[[int], int] = default_session_split_x,
    search_box_point_fn: Callable[[dict[str, Any]], tuple[int, int]] = default_search_box_point,
    region_for_point_fn: Callable[[int, int, tuple[int, int]], str] | None = None,
) -> dict[str, Any]:
    width, height = int(image_size[0]), int(image_size[1])
    safe_bounds = plus_entry_safe_bounds(image_size, split_x_fn=split_x_fn)
    candidates: list[dict[str, Any]] = []

    anchor_item = find_sidebar_search_anchor_item(ocr_items or [], image_size, split_x_fn=split_x_fn)
    if anchor_item is not None:
        anchor_bounds = item_bounds(anchor_item)
        anchor_center_x, anchor_center_y = item_center(anchor_item)
        raw_x = max(anchor_bounds[2] + 118, anchor_center_x + 148)
        raw_y = anchor_center_y
        point = clamp_point_to_bounds(int(raw_x), int(raw_y), safe_bounds)
        candidates.append(
            {
                "source": "sidebar_search_ocr_anchor",
                "text": str(anchor_item.get("text") or ""),
                "anchor_bounds": anchor_bounds,
                "point": list(point),
                "bounds": list(safe_bounds),
                "confidence": min(0.92, max(0.72, float(anchor_item.get("confidence") or 0.0) * 0.88)),
            }
        )

    current_x, current_y = windows_plus_point(geometry, split_x_fn=split_x_fn, search_box_point_fn=search_box_point_fn)
    current_point = clamp_point_to_bounds(current_x, current_y, safe_bounds)
    candidates.append(
        {
            "source": "windows_current_geometry",
            "point": list(current_point),
            "bounds": list(safe_bounds),
            "confidence": 0.74,
        }
    )
    reference_x, reference_y = windows_1080p_reference_plus_point(
        geometry,
        split_x_fn=split_x_fn,
        search_box_point_fn=search_box_point_fn,
    )
    reference_point = clamp_point_to_bounds(reference_x, reference_y, safe_bounds)
    candidates.append(
        {
            "source": "windows_1080p_reference_geometry",
            "point": list(reference_point),
            "bounds": list(safe_bounds),
            "confidence": 0.42,
            "reference_only": True,
        }
    )

    allowed_sources = {"sidebar_search_ocr_anchor", "windows_current_geometry"}
    if str(route_kind or "").lower() == "windows_1080p_reference":
        allowed_sources.add("windows_1080p_reference_geometry")
    eligible = [item for item in candidates if str(item.get("source") or "") in allowed_sources]
    selected = max(eligible, key=lambda item: float(item.get("confidence") or 0.0)) if eligible else candidates[0]
    selected_point = normalize_point(selected.get("point"))
    selected_source = str(selected.get("source") or "")
    selected_reason = "plus entry located from sidebar search OCR anchor"
    fallback_used = False
    fallback_reason = ""
    if selected_source == "windows_current_geometry":
        selected_reason = "plus entry fallback from current Windows sidebar geometry"
        fallback_used = True
        fallback_reason = "sidebar_search_ocr_anchor_not_available"
    elif selected_source == "windows_1080p_reference_geometry":
        selected_reason = "plus entry reference route fallback from Windows 1920x1080 geometry"
        fallback_used = True
        fallback_reason = "reference_route_or_no_current_locator"

    region = (
        region_for_point_fn(selected_point[0], selected_point[1], image_size)
        if region_for_point_fn
        else region_for_point(selected_point[0], selected_point[1], image_size, split_x_fn=split_x_fn)
    )
    target = make_locator_result(
        name="plus_entry",
        label=f"Step1 click target: plus entry beside search box ({route_kind or 'windows'})",
        strategy="multi_candidate_sidebar_plus_locator",
        region=region,
        bounds=safe_bounds,
        point=selected_point,
        candidates=candidates,
        selected_reason=selected_reason,
        confidence=float(selected.get("confidence") or 0.0),
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        source=selected_source,
        risk="single_click_plus_only_after_surface_preflight",
        metadata={
            "image_size": [width, height],
            "geometry": dict(geometry or {}),
            "route_kind": str(route_kind or "windows"),
            "verify_after_action": "plus_entry_popup_menu_detected",
            "layout_model": "add_friend_windows_adaptive_v1",
        },
    )
    target["platform_adapter"] = str(route_kind or "windows")
    target["item"] = item_snapshot(anchor_item, image_size) if anchor_item is not None else None
    return target


def invite_form_geometry_targets(
    image_size: tuple[int, int],
    *,
    region_for_point_fn: Callable[[int, int, tuple[int, int]], str] | None = None,
) -> dict[str, dict[str, Any]]:
    width, height = int(image_size[0]), int(image_size[1])
    input_left = int(max(24, width * 0.07))
    input_right = int(min(width - 24, width * 0.93))
    greeting_bounds = [
        input_left,
        int(max(78, height * 0.10)),
        input_right,
        int(min(height - 280, max(170, height * 0.24))),
    ]
    remark_bounds = [
        input_left,
        int(max(255, height * 0.31)),
        input_right,
        int(min(height - 190, max(335, height * 0.40))),
    ]
    confirm_bounds = [
        int(max(70, width * 0.23)),
        int(max(height - 86, height * 0.89)),
        int(min(width - 190, width * 0.50)),
        int(min(height - 18, height * 0.985)),
    ]
    greeting_x, greeting_y = center_of_bounds(greeting_bounds)
    remark_y = center_of_bounds(remark_bounds)[1]
    remark_x = int(min(max(remark_bounds[0] + 96, remark_bounds[0] + 16), remark_bounds[2] - 40))
    confirm_x, confirm_y = center_of_bounds(confirm_bounds)

    def region(x: int, y: int, fallback: str) -> str:
        if region_for_point_fn:
            return region_for_point_fn(x, y, image_size)
        return fallback

    return {
        "invite_greeting_textarea": make_locator_result(
            name="invite_greeting_textarea",
            label="发送添加朋友申请 textarea",
            strategy="window_region_geometry_fallback",
            region=region(greeting_x, greeting_y, "invite_form.verify_message"),
            bounds=greeting_bounds,
            point=[greeting_x, greeting_y],
            candidates=[{"source": "geometry_fallback", "bounds": normalize_bounds(greeting_bounds), "point": [greeting_x, greeting_y], "confidence": 0.62}],
            selected_reason="fixed invite form verify-message textarea region",
            confidence=0.62,
            fallback_used=True,
            fallback_reason="semantic_invite_form_anchor_not_available",
            source="fixed_invite_form_geometry",
            risk="clear_default_then_paste_verify_message",
            metadata={"image_size": [width, height], "layout_model": "add_friend_invite_form_v1"},
        ),
        "invite_remark_input": make_locator_result(
            name="invite_remark_input",
            label="备注 input",
            strategy="window_region_geometry_fallback",
            region=region(remark_x, remark_y, "invite_form.remark_name"),
            bounds=remark_bounds,
            point=[remark_x, remark_y],
            candidates=[{"source": "geometry_fallback", "bounds": normalize_bounds(remark_bounds), "point": [remark_x, remark_y], "confidence": 0.62}],
            selected_reason="left-biased fixed remark input point avoids border focus loss",
            confidence=0.62,
            fallback_used=True,
            fallback_reason="semantic_invite_form_anchor_not_available",
            source="fixed_invite_form_geometry",
            risk="clear_default_then_paste_remark_name",
            metadata={"image_size": [width, height], "layout_model": "add_friend_invite_form_v1"},
        ),
        "invite_confirm_button": make_locator_result(
            name="invite_confirm_button",
            label="确定 button",
            strategy="window_region_geometry_fallback",
            region=region(confirm_x, confirm_y, "invite_form.confirm_button"),
            bounds=confirm_bounds,
            point=[confirm_x, confirm_y],
            candidates=[{"source": "geometry_fallback", "bounds": normalize_bounds(confirm_bounds), "point": [confirm_x, confirm_y], "confidence": 0.62}],
            selected_reason="fixed lower-left green confirm button region",
            confidence=0.62,
            fallback_used=True,
            fallback_reason="semantic_invite_form_anchor_not_available",
            source="fixed_invite_form_geometry",
            risk="click_confirm_after_text_review",
            metadata={"image_size": [width, height], "layout_model": "add_friend_invite_form_v1"},
        ),
    }


def semantic_invite_form_targets(
    image_size: tuple[int, int],
    ocr_items: list[dict[str, Any]] | None,
    *,
    region_for_point_fn: Callable[[int, int, tuple[int, int]], str] | None = None,
) -> dict[str, dict[str, Any]]:
    width, height = int(image_size[0]), int(image_size[1])
    targets = invite_form_geometry_targets(image_size, region_for_point_fn=region_for_point_fn)
    items = [item for item in (ocr_items or []) if isinstance(item, dict)]

    def region(x: int, y: int, fallback: str) -> str:
        if region_for_point_fn:
            return region_for_point_fn(x, y, image_size)
        return fallback

    greeting_anchor = find_best_text_item(items, ("发送添加朋友申请", "朋友申请", "申请"), image_size=image_size, max_y_ratio=0.34)
    if greeting_anchor is not None:
        bounds = item_bounds(greeting_anchor)
        field_bounds = normalize_bounds(
            [
                max(18, bounds[0] - 18),
                min(height - 80, bounds[3] + 8),
                min(width - 18, max(bounds[2] + 160, int(width * 0.92))),
                min(height - 190, max(bounds[3] + 84, int(height * 0.22))),
            ]
        )
        point = center_of_bounds(field_bounds)
        targets["invite_greeting_textarea"] = make_semantic_target(
            name="invite_greeting_textarea",
            label="发送添加朋友申请 textarea",
            region=region(point[0], point[1], "invite_form.verify_message"),
            bounds=field_bounds,
            point=point,
            anchor=greeting_anchor,
            selected_reason="semantic anchor: 发送添加朋友申请",
            source="ocr_invite_greeting_label_anchor",
            risk="clear_default_then_paste_verify_message",
            image_size=image_size,
        )

    remark_anchor = find_best_text_item(items, ("备注名", "备注"), image_size=image_size, min_y_ratio=0.18, max_y_ratio=0.72)
    if remark_anchor is not None:
        bounds = item_bounds(remark_anchor)
        field_bounds = normalize_bounds(
            [
                max(18, bounds[0] - 18),
                min(height - 130, bounds[3] + 8),
                min(width - 18, max(bounds[2] + 170, int(width * 0.92))),
                min(height - 80, max(bounds[3] + 64, int(height * 0.39))),
            ]
        )
        point = [int(min(max(field_bounds[0] + 96, field_bounds[0] + 16), field_bounds[2] - 28)), center_of_bounds(field_bounds)[1]]
        targets["invite_remark_input"] = make_semantic_target(
            name="invite_remark_input",
            label="备注 input",
            region=region(point[0], point[1], "invite_form.remark_name"),
            bounds=field_bounds,
            point=point,
            anchor=remark_anchor,
            selected_reason="semantic anchor: 备注",
            source="ocr_invite_remark_label_anchor",
            risk="clear_default_then_paste_remark_name",
            image_size=image_size,
        )

    confirm_anchor = find_best_text_item(items, ("确定", "完成", "发送"), image_size=image_size, min_y_ratio=0.70)
    if confirm_anchor is not None:
        bounds = item_bounds(confirm_anchor)
        point = item_center(confirm_anchor)
        click_bounds = normalize_bounds(
            [
                max(8, bounds[0] - 42),
                max(8, bounds[1] - 20),
                min(width - 8, bounds[2] + 42),
                min(height - 8, bounds[3] + 20),
            ]
        )
        targets["invite_confirm_button"] = make_semantic_target(
            name="invite_confirm_button",
            label="确定 button",
            region=region(point[0], point[1], "invite_form.confirm_button"),
            bounds=click_bounds,
            point=point,
            anchor=confirm_anchor,
            selected_reason="semantic anchor: 确定",
            source="ocr_invite_confirm_button_anchor",
            risk="click_confirm_after_text_review",
            image_size=image_size,
        )

    return targets


def make_semantic_target(
    *,
    name: str,
    label: str,
    region: str,
    bounds: list[int],
    point: list[int] | tuple[int, int],
    anchor: dict[str, Any],
    selected_reason: str,
    source: str,
    risk: str,
    image_size: tuple[int, int],
) -> dict[str, Any]:
    anchor_confidence = float(anchor.get("confidence") or 0.0)
    confidence = min(0.94, max(0.76, anchor_confidence * 0.92 if anchor_confidence else 0.78))
    target = make_locator_result(
        name=name,
        label=label,
        strategy="semantic_ocr_anchor_locator",
        region=region,
        bounds=bounds,
        point=point,
        candidates=[
            {
                "source": source,
                "anchor_text": str(anchor.get("text") or ""),
                "anchor_bounds": item_bounds(anchor),
                "point": normalize_point(point),
                "bounds": normalize_bounds(bounds),
                "confidence": confidence,
            }
        ],
        selected_reason=selected_reason,
        confidence=confidence,
        fallback_used=False,
        fallback_reason="",
        source=source,
        risk=risk,
        metadata={"image_size": [int(image_size[0]), int(image_size[1])], "layout_model": "add_friend_invite_form_v1"},
    )
    target["item"] = item_snapshot(anchor, image_size)
    return target


def find_best_text_item(
    items: list[dict[str, Any]],
    tokens: tuple[str, ...],
    *,
    image_size: tuple[int, int] | None = None,
    min_y_ratio: float = 0.0,
    max_y_ratio: float = 1.0,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for item in items:
        text = compact_ocr_text(item.get("text"))
        if not text:
            continue
        matched = any(compact_ocr_text(token) in text for token in tokens)
        if not matched:
            continue
        center_x, center_y = item_center(item)
        image_height = int(image_size[1]) if image_size else int(item.get("image_height") or item.get("source_image_height") or 0)
        if image_height <= 1:
            image_height = 1
        ratio = center_y / image_height
        if ratio < min_y_ratio or ratio > max_y_ratio:
            continue
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (float(item.get("confidence") or 0.0), len(str(item.get("text") or ""))))


def field_text_visible(expected: str, ocr_items: list[dict[str, Any]] | None) -> dict[str, Any]:
    clean_expected = compact_ocr_text(expected)
    surface = "\n".join(compact_ocr_text(item.get("text")) for item in (ocr_items or []) if isinstance(item, dict))
    digits_expected = "".join(ch for ch in str(expected or "") if ch.isdigit())
    digits_surface = "".join(ch for ch in surface if ch.isdigit())
    ok = bool(clean_expected and clean_expected in surface) or bool(digits_expected and digits_expected in digits_surface)
    return {
        "ok": ok,
        "expected_length": len(str(expected or "")),
        "matched_by": "ocr_text" if clean_expected and clean_expected in surface else "digits" if digits_expected and digits_expected in digits_surface else "",
    }


def invite_form_field_verification(
    *,
    verify_message: str,
    remark_name: str,
    remark_code: str,
    ocr_items: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    verify_result = field_text_visible(verify_message, ocr_items)
    remark_result = field_text_visible(remark_name, ocr_items)
    code_result = field_text_visible(remark_code, ocr_items)
    return {
        "ok": bool(verify_result.get("ok")) and bool(remark_result.get("ok")) and bool(code_result.get("ok")),
        "verify_message": verify_result,
        "remark_name": remark_result,
        "remark_code": code_result,
        "method": "ocr_surface_text_visibility",
    }
