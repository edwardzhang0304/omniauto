"""Focused checks for no-blind-click evidence helpers."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr import interaction_evidence
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr import window_layout
from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar as sidecar


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def _production_layout_snapshot() -> dict[str, object]:
    image = Image.new("RGB", (980, 860), (247, 247, 247))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 70, 859], fill=(224, 224, 224))
    draw.rectangle([71, 0, 370, 89], fill=(210, 210, 210))
    draw.rectangle([71, 90, 370, 859], fill=(240, 240, 240))
    draw.rectangle([371, 0, 979, 89], fill=(238, 238, 238))
    draw.rectangle([371, 90, 979, 759], fill=(255, 255, 255))
    draw.rectangle([371, 760, 979, 859], fill=(242, 242, 242))
    draw.line([(70, 0), (70, 859)], fill=(110, 110, 110), width=2)
    draw.line([(370, 0), (370, 859)], fill=(110, 110, 110), width=2)
    draw.line([(71, 89), (979, 89)], fill=(110, 110, 110), width=2)
    draw.line([(371, 759), (979, 759)], fill=(110, 110, 110), width=2)
    structural = window_layout.build_structural_layout_regions(image)
    assert_true(structural.get("ok") is True, f"production layout builder rejected fixture: {structural}")
    return window_layout.build_layout_snapshot(
        hwnd=1001,
        frame_id=window_layout.new_frame_id(1001),
        capture_mode=window_layout.CAPTURE_MODE_WINDOW_VISIBLE_SCREEN,
        image_size=image.size,
        capture_screen_origin=[0, 0],
        window_rect=[0, 0, 980, 860],
        client_rect=[0, 0, 980, 860],
        client_screen_origin=[0, 0],
        dpi_scale=1.0,
        regions=structural.get("regions") or {},
        anchors=structural.get("anchors") or [],
        confidence=float(structural.get("confidence") or 0.0),
        conflicts=structural.get("conflicts") or [],
        executable=bool(structural.get("ok")),
    )


def test_missing_or_failed_probe_never_authorizes_click() -> None:
    missing = interaction_evidence.input_surface_click_evidence({"has_visible_text": False, "reason": "input_region_blank"})
    failed = interaction_evidence.input_surface_click_evidence(
        {"has_visible_text": False, "reason": "input_region_blank", "bounds": [400, 680, 880, 800], "error": "capture_failed"}
    )
    assert_true(missing.get("ok") is False and "evidence" in str(missing.get("reason")), f"missing bounds must block: {missing}")
    assert_true(failed.get("ok") is False and "probe_failed" in str(failed.get("reason")), f"failed probe must block: {failed}")


def test_verified_clicks_stay_inside_observed_interior_with_variation() -> None:
    evidence = interaction_evidence.input_surface_click_evidence(
        {"has_visible_text": False, "reason": "input_region_blank", "bounds": [394, 677, 886, 799]}
    )
    assert_true(evidence.get("ok") is True, f"valid observed input surface should pass: {evidence}")
    points: set[tuple[int, int]] = set()
    for seed in range(60):
        random.seed(seed)
        selected = interaction_evidence.choose_input_click_point(evidence, random_module=random)
        assert_true(selected.get("ok") is True, f"verified evidence should select a point: {selected}")
        x, y = selected["point"]
        left, top, right, bottom = evidence["click_bounds"]
        assert_true(left <= x < right and top <= y < bottom, f"point escaped evidence bounds: {selected}")
        points.add((x, y))
    assert_true(len(points) >= 24, f"verified point selection lacks variation: {len(points)}")


def test_missing_input_bounds_causes_zero_rpa_clicks() -> None:
    originals = {
        "activate_window": sidecar.activate_window,
        "recover_send_window_guard": sidecar.recover_send_window_guard,
        "capture_wechat": sidecar.capture_wechat,
        "run_ocr_for_input_region_probe": sidecar.run_ocr_for_input_region_probe,
        "input_text_region_state": sidecar.input_text_region_state,
        "human_client_click": sidecar.human_client_click,
        "time_sleep": sidecar.time.sleep,
    }
    calls = {"click": 0}
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    try:
        sidecar.activate_window = lambda *_args, **_kwargs: True
        sidecar.recover_send_window_guard = lambda *_args, **_kwargs: {"ok": True, "reason": "window_valid"}
        sidecar.capture_wechat = lambda *_args, **_kwargs: (object(), "input.png")
        sidecar.run_ocr_for_input_region_probe = lambda *_args, **_kwargs: ([], "roi")
        sidecar.input_text_region_state = lambda *_args, **_kwargs: {"has_visible_text": False, "reason": "input_region_blank"}
        sidecar.human_client_click = lambda *_args, **_kwargs: calls.__setitem__("click", calls["click"] + 1)
        sidecar.time.sleep = lambda _seconds: None
        result = sidecar.paste_text_with_confirmation(
            1001,
            "测试输入",
            points={"input_point": [637, 715], "send_point": [919, 816]},
            geometry=geometry,
            settings={"enabled": True, "method": "sendinput_unicode"},
        )
        assert_true(result.get("ok") is False, f"missing evidence must stop input: {result}")
        assert_true(result.get("reason") == "input_click_evidence_missing_before_type", f"wrong failure: {result}")
        assert_true(calls["click"] == 0, f"missing input bounds must cause zero clicks: {calls}")
    finally:
        for name, value in originals.items():
            if name == "time_sleep":
                sidecar.time.sleep = value
            else:
                setattr(sidecar, name, value)


def test_visual_send_forwards_verified_bounds_through_real_click_mapping() -> None:
    hwnd = 1001
    snapshot = _production_layout_snapshot()
    snapshot_id = str(snapshot.get("layout_snapshot_id") or "")
    input_bounds = list(snapshot.get("input_bounds") or [])
    assert_true(snapshot_id != "" and len(input_bounds) == 4, f"invalid production snapshot fixture: {snapshot}")
    expected_click_evidence = interaction_evidence.input_surface_click_evidence(
        {
            "has_visible_text": False,
            "reason": "input_region_blank",
            "bounds": input_bounds,
        }
    )
    expected_click_bounds = list(expected_click_evidence.get("click_bounds") or [])
    assert_true(len(expected_click_bounds) == 4, f"invalid input click evidence: {expected_click_evidence}")
    geometry = {
        "left": 0,
        "top": 0,
        "right": 980,
        "bottom": 860,
        "width": 980,
        "height": 860,
    }
    client_geometry = {
        **geometry,
        "screen_left": 0,
        "screen_top": 0,
    }
    originals = {
        "get_window_geometry": sidecar.get_window_geometry,
        "get_window_client_geometry": sidecar.get_window_client_geometry,
        "window_dpi_scale": sidecar.window_dpi_scale,
        "require_active_ui_action_budget": sidecar.require_active_ui_action_budget,
        "activate_window": sidecar.activate_window,
        "ensure_left_button_released": sidecar.ensure_left_button_released,
        "human_screen_click_in_bounds": sidecar.human_screen_click_in_bounds,
        "recover_send_window_guard": sidecar.recover_send_window_guard,
        "type_text_with_sendinput_unicode": sidecar.type_text_with_sendinput_unicode,
        "capture_wechat": sidecar.capture_wechat,
        "input_text_region_state": sidecar.input_text_region_state,
        "input_region_visual_delta_confirms": sidecar.input_region_visual_delta_confirms,
        "clipboard_read": sidecar.clipboard_read,
        "clipboard_copy": sidecar.clipboard_copy,
        "hotkey": sidecar.hotkey,
        "key_press": sidecar.key_press,
        "humanized_action_sleep": sidecar.humanized_action_sleep,
        "humanized_sleep_ms": sidecar.humanized_sleep_ms,
        "time_sleep": sidecar.time.sleep,
    }
    old_fast_confirm = os.environ.get("WECHAT_WIN32_OCR_INPUT_FAST_VISUAL_CONFIRM")
    physical_clicks: list[dict[str, object]] = []
    pressed_keys: list[int] = []
    post_input_frame = Image.new("RGB", (980, 860), "white")
    sidecar.invalidate_all_layout_snapshots(reason="verified_bounds_bridge_test_setup")
    sidecar._LAYOUT_SNAPSHOT_STORE.put(snapshot)
    sidecar._LATEST_LAYOUT_SNAPSHOT_BY_HWND[hwnd] = snapshot_id
    try:
        os.environ["WECHAT_WIN32_OCR_INPUT_FAST_VISUAL_CONFIRM"] = "1"
        sidecar.get_window_geometry = lambda *_args, **_kwargs: dict(geometry)
        sidecar.get_window_client_geometry = lambda *_args, **_kwargs: dict(client_geometry)
        sidecar.window_dpi_scale = lambda *_args, **_kwargs: 1.0
        sidecar.require_active_ui_action_budget = lambda *_args, **_kwargs: None
        sidecar.activate_window = lambda *_args, **_kwargs: True
        sidecar.ensure_left_button_released = lambda *_args, **_kwargs: None

        def physical_click(screen_x: int, screen_y: int, *, bounds: list[int], action_name: str) -> dict[str, object]:
            physical_clicks.append(
                {
                    "point": [int(screen_x), int(screen_y)],
                    "bounds": list(bounds),
                    "action_name": action_name,
                }
            )
            return {"ok": True}

        sidecar.human_screen_click_in_bounds = physical_click
        sidecar.recover_send_window_guard = lambda *_args, **_kwargs: {"ok": True, "reason": "window_valid"}
        sidecar.type_text_with_sendinput_unicode = lambda text, *_args, **_kwargs: {
            "ok": True,
            "method": "sendinput_unicode",
            "typed_chars": len(text),
        }
        def capture_after_input(*_args, **_kwargs):
            refreshed = _production_layout_snapshot()
            refreshed_id = str(refreshed.get("layout_snapshot_id") or "")
            sidecar._LAYOUT_SNAPSHOT_STORE.put(refreshed)
            sidecar._LATEST_LAYOUT_SNAPSHOT_BY_HWND[hwnd] = refreshed_id
            sidecar._LAYOUT_SNAPSHOT_ID_BY_IMAGE_ID[id(post_input_frame)] = refreshed_id
            return post_input_frame, "send_input_probe_1.png"

        sidecar.capture_wechat = capture_after_input
        sidecar.input_text_region_state = lambda *_args, **_kwargs: {
            "has_visible_text": True,
            "reason": "ocr_or_dark_pixels",
            "bounds": input_bounds,
            "dark_ratio": 0.025,
        }
        sidecar.input_region_visual_delta_confirms = lambda *_args, **_kwargs: {
            "ok": True,
            "reason": "input_area_visual_delta",
        }
        sidecar.clipboard_read = lambda: "真实边界传递"
        sidecar.clipboard_copy = lambda *_args, **_kwargs: None
        sidecar.hotkey = lambda *_args, **_kwargs: None
        sidecar.key_press = lambda key: pressed_keys.append(int(key))
        sidecar.humanized_action_sleep = lambda *_args, **_kwargs: None
        sidecar.humanized_sleep_ms = lambda *_args, **_kwargs: None
        result = sidecar.send_with_visual_input(
            hwnd,
            "真实边界传递",
            geometry=geometry,
            settings={"enabled": True, "method": "sendinput_unicode"},
            before_input_region_seed={
                "input_region": {
                    "has_visible_text": False,
                    "reason": "input_region_blank",
                    "bounds": input_bounds,
                }
            },
            before_send_trigger_check=lambda **_kwargs: {"ok": True},
        )
        assert_true(result.get("ok") is True, f"real send connector rejected verified bounds: {result}")
        assert_true(len(physical_clicks) == 2, f"expected input and focus-proof clicks: {physical_clicks}")
        input_click, focus_proof_click = physical_clicks
        assert_true(input_click.get("action_name") == "human_window_image_click", f"wrong click boundary: {input_click}")
        assert_true(input_click.get("bounds") == expected_click_bounds, f"verified input bounds were not mapped to physical click: {input_click}")
        assert_true(focus_proof_click.get("bounds") == input_bounds, f"fresh input snapshot did not reach focus proof: {focus_proof_click}")
        assert_true(pressed_keys == [sidecar.win32con.VK_RETURN], f"real send trigger did not reach Enter boundary: {pressed_keys}")
    finally:
        sidecar.invalidate_all_layout_snapshots(reason="verified_bounds_bridge_test_cleanup")
        sidecar._LATEST_LAYOUT_SNAPSHOT_BY_HWND.pop(hwnd, None)
        if old_fast_confirm is None:
            os.environ.pop("WECHAT_WIN32_OCR_INPUT_FAST_VISUAL_CONFIRM", None)
        else:
            os.environ["WECHAT_WIN32_OCR_INPUT_FAST_VISUAL_CONFIRM"] = old_fast_confirm
        for name, value in originals.items():
            if name == "time_sleep":
                sidecar.time.sleep = value
            else:
                setattr(sidecar, name, value)


def test_missing_search_label_causes_zero_rpa_actions() -> None:
    originals = {
        "basic_send_window_guard": sidecar.basic_send_window_guard,
        "get_window_geometry": sidecar.get_window_geometry,
        "capture_wechat": sidecar.capture_wechat,
        "run_ocr_traced": sidecar.run_ocr_traced,
        "target_switch_surface_state": sidecar.target_switch_surface_state,
        "human_window_image_click_in_bounds": sidecar.human_window_image_click_in_bounds,
        "key_press": sidecar.key_press,
    }
    calls = {"click": 0, "key": 0}
    try:
        sidecar.basic_send_window_guard = lambda *_args, **_kwargs: {"ok": True, "reason": "window_valid"}
        sidecar.get_window_geometry = lambda *_args, **_kwargs: {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
        sidecar.capture_wechat = lambda *_args, **_kwargs: (object(), "search.png")
        sidecar.run_ocr_traced = lambda *_args, **_kwargs: []
        sidecar.target_switch_surface_state = lambda *_args, **_kwargs: {"ok": True, "reason": "surface_ready"}
        sidecar.human_window_image_click_in_bounds = lambda *_args, **_kwargs: calls.__setitem__("click", calls["click"] + 1)
        sidecar.key_press = lambda *_args, **_kwargs: calls.__setitem__("key", calls["key"] + 1)
        result = sidecar.clear_sidebar_search_box_without_select_all(1001, 122, 64, target_hint="新数据测试")
        assert_true(result.get("ok") is False, f"missing search label must stop: {result}")
        assert_true(result.get("reason") == "search_box_evidence_missing_before_click", f"wrong failure: {result}")
        assert_true(calls == {"click": 0, "key": 0}, f"missing search evidence must cause zero actions: {calls}")
    finally:
        for name, value in originals.items():
            setattr(sidecar, name, value)


def test_observed_search_placeholder_variants_are_accepted_in_sidebar_only() -> None:
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    layout_snapshot = _production_layout_snapshot()
    placeholder = {
        "text": "Q\u641c\u7d22",
        "left": 101,
        "top": 61,
        "right": 143,
        "bottom": 83,
    }
    evidence = sidecar.sidebar_search_box_evidence(
        [placeholder],
        geometry=geometry,
        layout_snapshot=layout_snapshot,
    )
    assert_true(evidence.get("ok") is True, f"known placeholder OCR variant must be accepted: {evidence}")
    outside_sidebar = dict(placeholder, left=522, right=563)
    outside = sidecar.sidebar_search_box_evidence(
        [outside_sidebar],
        geometry=geometry,
        layout_snapshot=layout_snapshot,
    )
    assert_true(outside.get("ok") is False, f"search-like text outside sidebar must remain blocked: {outside}")


def main() -> int:
    tests = [
        test_missing_or_failed_probe_never_authorizes_click,
        test_verified_clicks_stay_inside_observed_interior_with_variation,
        test_missing_input_bounds_causes_zero_rpa_clicks,
        test_visual_send_forwards_verified_bounds_through_real_click_mapping,
        test_missing_search_label_causes_zero_rpa_actions,
        test_observed_search_placeholder_variants_are_accepted_in_sidebar_only,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} Win32/OCR interaction evidence checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
