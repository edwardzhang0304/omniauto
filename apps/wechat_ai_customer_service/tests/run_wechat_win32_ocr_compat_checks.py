"""Regression checks for the WeChat Win32/OCR compatibility adapter."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters.wechat_connector import compat_args, parse_json_object  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar import (  # noqa: E402
    calculate_send_points,
    parse_messages_from_ocr,
    parse_sessions_from_ocr,
    rect_in_input_area,
    rect_in_input_toolbar,
    send_rate_decision,
    select_uia_edit_control,
    select_uia_send_button,
    validate_send_geometry,
)
from apps.wechat_ai_customer_service.admin_backend.services.wechat_startup_check import evaluate_wechat_capability  # noqa: E402


class FakeControl:
    def __init__(self, *, name: str, control_type: str, rect: object, class_name: str = "") -> None:
        self.Name = name
        self.ControlTypeName = control_type
        self.BoundingRectangle = rect
        self.ClassName = class_name


class FakeRect:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_parse_sessions_from_ocr() -> None:
    items = [
        {"text": "Q搜索", "confidence": 0.99, "left": 110, "right": 170, "top": 55, "bottom": 80, "center_x": 140, "center_y": 68},
        {"text": "文件传输助手", "confidence": 0.99, "left": 155, "right": 260, "top": 117, "bottom": 140, "center_x": 205, "center_y": 128},
        {"text": "星期三", "confidence": 0.99, "left": 280, "right": 322, "top": 119, "bottom": 138, "center_x": 301, "center_y": 128},
        {"text": "您想今天定，我完全理...", "confidence": 0.96, "left": 154, "right": 316, "top": 143, "bottom": 165, "center_x": 235, "center_y": 154},
        {"text": "许聪", "confidence": 0.99, "left": 154, "right": 195, "top": 198, "bottom": 221, "center_x": 174, "center_y": 209},
        {"text": "[图片]", "confidence": 0.96, "left": 154, "right": 200, "top": 225, "bottom": 247, "center_x": 177, "center_y": 236},
        {"text": "新数据测试", "confidence": 0.99, "left": 154, "right": 247, "top": 361, "bottom": 385, "center_x": 200, "center_y": 373},
        {"text": "[文件] recorder_expor...", "confidence": 0.96, "left": 157, "right": 321, "top": 388, "bottom": 408, "center_x": 239, "center_y": 398},
    ]
    sessions = parse_sessions_from_ocr(items, (641, 919))
    names = [item["name"] for item in sessions]
    assert_true(names == ["文件传输助手", "许聪", "新数据测试"], f"unexpected sessions: {names}")


def test_parse_messages_from_ocr() -> None:
    items = [
        {"text": "新数据测试(2)", "confidence": 0.99, "left": 350, "right": 450, "top": 55, "bottom": 80, "center_x": 400, "center_y": 68},
        {"text": "星期三03:02", "confidence": 0.99, "left": 516, "right": 609, "top": 594, "bottom": 614, "center_x": 562, "center_y": 604},
        {"text": "高频漏采实盘测试 订测试耗材1", "confidence": 0.98, "left": 441, "right": 640, "top": 652, "bottom": 672, "center_x": 540, "center_y": 662},
        {"text": "1个 1元", "confidence": 0.98, "left": 439, "right": 520, "top": 674, "bottom": 698, "center_x": 480, "center_y": 686},
    ]
    messages = parse_messages_from_ocr(items, (641, 919), target="新数据测试")
    assert_true(len(messages) == 1, f"unexpected message count: {messages}")
    assert_true("订测试耗材1" in messages[0]["content"], f"message content not merged: {messages}")
    assert_true(messages[0]["sender"] == "self", f"right-side message should be self: {messages}")


def test_parse_messages_keeps_low_visible_bubble_lines() -> None:
    items = [
        {"text": "长订单第一行", "confidence": 0.98, "left": 440, "right": 610, "top": 712, "bottom": 736, "center_x": 525, "center_y": 724},
        {"text": "末尾价格 324元", "confidence": 0.98, "left": 440, "right": 610, "top": 782, "bottom": 806, "center_x": 525, "center_y": 794},
        {"text": "发送", "confidence": 0.99, "left": 560, "right": 610, "top": 850, "bottom": 876, "center_x": 585, "center_y": 863},
    ]
    messages = parse_messages_from_ocr(items, (641, 919), target="新数据测试")
    content = "\n".join(item["content"] for item in messages)
    assert_true("末尾价格 324元" in content, f"low visible bubble line should be retained: {messages}")
    assert_true("发送" not in content, f"send button noise should still be filtered: {messages}")


def test_connector_helpers() -> None:
    args = compat_args(["sessions", "--fresh"])
    assert_true(args == ["sessions"], f"--fresh should be omitted for compat sidecar: {args}")
    payload = parse_json_object("library log\n{\"ok\": true, \"nested\": {\"a\": 1}}")
    assert_true(payload == {"ok": True, "nested": {"a": 1}}, f"failed to parse logged JSON: {payload}")


def test_send_geometry_guard() -> None:
    unsafe = {"width": 650, "height": 1100}
    safe = {"width": 801, "height": 1149}
    assert_true(validate_send_geometry(unsafe)["ok"] is False, "small WeChat window should be blocked")
    points = calculate_send_points(safe)
    assert_true(points["ok"] is True, f"safe geometry should produce points: {points}")
    assert_true(points["input_point"][1] > 900, f"input point should stay in text area: {points}")
    assert_true(points["send_point"][1] > 1000, f"send point should stay near send button: {points}")


def test_send_rate_guard() -> None:
    state = {"events": [{"target": "新数据测试", "at": 100.0}]}
    limited = send_rate_decision(
        state,
        target="新数据测试",
        now_ts=120.0,
        min_interval_seconds=30,
        burst_window_seconds=600,
        burst_limit=5,
    )
    assert_true(limited["ok"] is False and limited["reason"] == "min_interval_not_elapsed", f"expected interval block: {limited}")
    burst = send_rate_decision(
        {"events": [{"target": "新数据测试", "at": value} for value in (100, 150, 200, 250, 300)]},
        target="新数据测试",
        now_ts=350.0,
        min_interval_seconds=0,
        burst_window_seconds=600,
        burst_limit=5,
    )
    assert_true(burst["ok"] is False and burst["reason"] == "burst_limit_reached", f"expected burst block: {burst}")


def test_uia_control_selection_prefers_chatbox() -> None:
    geometry = {"left": 0, "top": 0, "width": 801, "height": 1149}
    edit = FakeControl(name="", control_type="EditControl", rect=FakeRect(345, 970, 770, 1085))
    search = FakeControl(name="搜索", control_type="EditControl", rect=FakeRect(95, 55, 275, 90))
    send = FakeControl(name="发送", control_type="ButtonControl", rect=FakeRect(690, 1082, 766, 1125))
    attach = FakeControl(name="文件", control_type="ButtonControl", rect=FakeRect(440, 1082, 475, 1125))
    assert_true(rect_in_input_area({"left": 345, "top": 970, "right": 770, "bottom": 1085}, geometry), "chat edit should be inside input area")
    assert_true(rect_in_input_toolbar({"left": 690, "top": 1082, "right": 766, "bottom": 1125}, geometry), "send button should be inside toolbar")
    assert_true(select_uia_edit_control([search, edit], geometry) is edit, "chat edit should beat search box")
    assert_true(select_uia_send_button([attach, send], geometry) is send, "send button should be selected by name")


def test_startup_capability_decision() -> None:
    offline = evaluate_wechat_capability(
        {"online": False, "scheme": "wechat_not_ready", "receive": {"ok": False}, "send": {"ok": False}},
        require_send=True,
        module_name="微信自动客服",
    )
    assert_true(offline["ok"] is False and offline["detail"] == "wechat_not_ready", f"offline should block startup: {offline}")

    receive_only = {
        "online": True,
        "scheme": "win32_ocr_receive_only",
        "adapter": "win32_ocr",
        "receive": {"ok": True},
        "send": {"ok": False},
    }
    recorder = evaluate_wechat_capability(receive_only, require_send=False, module_name="AI智能记录员")
    service = evaluate_wechat_capability(receive_only, require_send=True, module_name="微信自动客服")
    assert_true(recorder["ok"] is True, f"recorder can run with receive-only transport: {recorder}")
    assert_true(service["ok"] is False and service["detail"] == "wechat_send_unavailable", f"customer service requires send: {service}")

    wxauto = evaluate_wechat_capability({"online": True, "adapter": "wxauto4", "scheme": "wxauto4"}, require_send=True, module_name="微信自动客服")
    assert_true(wxauto["ok"] is True and wxauto["scheme"] == "wxauto4", f"wxauto4 should pass startup: {wxauto}")


def main() -> int:
    tests = [
        test_parse_sessions_from_ocr,
        test_parse_messages_from_ocr,
        test_parse_messages_keeps_low_visible_bubble_lines,
        test_connector_helpers,
        test_send_geometry_guard,
        test_send_rate_guard,
        test_uia_control_selection_prefers_chatbox,
        test_startup_capability_decision,
    ]
    passed = 0
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
        passed += 1
    print(f"All {passed} WeChat Win32/OCR compatibility checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
