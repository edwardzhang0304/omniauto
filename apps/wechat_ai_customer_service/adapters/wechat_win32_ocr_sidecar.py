"""Win32/OCR fallback sidecar for the WeChat desktop recorder.

The primary adapter uses wxauto4, which is fast and structured when it can
attach to WeChat. Recent WeChat 4.x builds may change enough UI internals that
wxauto4 cannot initialize even though the logged-in main window is visible.
This sidecar keeps the recorder usable by relying only on the top-level Win32
window, screenshots, OCR, clipboard paste, and clicks.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
import random
import re
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

try:
    import pyperclip as _pyperclip
except Exception:  # pragma: no cover - optional clipboard convenience package.
    _pyperclip = None

try:
    import win32api
    import win32con
    import win32gui
    _WIN32_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - allows pure parser tests without pywin32.
    win32api = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    _WIN32_IMPORT_ERROR = repr(exc)

    class _Win32ConFallback:
        VK_CONTROL = 0x11
        VK_RETURN = 0x0D
        MOUSEEVENTF_MOVE = 0x0001
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004

    win32con = _Win32ConFallback()  # type: ignore[assignment]
from PIL import ImageGrab

try:
    from rapidocr_onnxruntime import RapidOCR
    _OCR_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - OCR is only needed for live sidecar actions.
    RapidOCR = None  # type: ignore[assignment]
    _OCR_IMPORT_ERROR = repr(exc)


SEARCH_BOX_REL = (110, 70)
SESSION_CLICK_X = 260
CHAT_HEADER_MAX_Y = 90
CHAT_INPUT_BOTTOM_OFFSET = 52
DEFAULT_MESSAGE_BOTTOM_EXCLUDE_PX = 95
OCR_MIN_CONFIDENCE = 0.45
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SEND_GUARD_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_send_guard.json"
MIN_SEND_CLIENT_WIDTH = 700
MIN_SEND_CLIENT_HEIGHT = 720
DEFAULT_SEND_MIN_INTERVAL_SECONDS = 30
DEFAULT_SEND_BURST_WINDOW_SECONDS = 600
DEFAULT_SEND_BURST_LIMIT = 5
DEFAULT_SEND_MODE = "uia_first"
BLOCKING_SCREEN_TOKENS = (
    "登录",
    "扫码",
    "选择文件",
    "文件名无效",
    "安全验证",
    "账号安全",
    "登录环境异常",
    "操作频繁",
    "拖拽",
)

_OCR_ENGINE: RapidOCR | None = None


def clipboard_copy(text: str) -> None:
    if _pyperclip is not None:
        _pyperclip.copy(text)
        return
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return
    except Exception as exc:
        raise RuntimeError("clipboard_copy_unavailable: install pyperclip or enable tkinter clipboard support") from exc


def main() -> int:
    configure_dpi_awareness()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "capabilities", "sessions", "messages", "send"], nargs="?")
    parser.add_argument("--target", help="Chat name for messages/send.")
    parser.add_argument("--text", help="Message text for send.")
    parser.add_argument("--exact", action="store_true", help="Use exact chat name matching.")
    parser.add_argument("--history-load-times", type=int, default=0, help="Scroll upward this many times before reading messages.")
    parser.add_argument("--artifact-dir", help="Optional directory for debug screenshots.")
    args = parser.parse_args()

    captured = io.StringIO()
    try:
        payload = run_action(args)
    except Exception as exc:
        payload = {"ok": False, "online": False, "state": "win32_ocr_failed", "error": repr(exc)}

    logs = captured.getvalue().strip()
    if logs:
        payload["library_stdout"] = logs
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


def run_action(args: argparse.Namespace) -> dict[str, Any]:
    if _WIN32_IMPORT_ERROR:
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "pywin32_unavailable",
            "error": _WIN32_IMPORT_ERROR,
        }
    probe = ensure_visible_wechat_window()
    if not probe.get("visible_main_windows"):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "main_window_not_found",
            "window_probe": probe,
            "error": "No visible WeChat main window was found.",
        }
    window = probe["visible_main_windows"][0]
    hwnd = int(window.get("hwnd") or 0)
    if not hwnd:
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "main_window_not_found",
            "window_probe": probe,
            "error": "Visible WeChat window did not expose an hwnd.",
        }

    activate_window(hwnd)
    time.sleep(0.2)
    if args.action == "status":
        return status_payload(hwnd, probe, artifact_dir=args.artifact_dir)
    if args.action == "capabilities":
        return capabilities_payload(hwnd, probe, artifact_dir=args.artifact_dir)
    if args.action == "sessions":
        return sessions_payload(hwnd, probe, artifact_dir=args.artifact_dir)
    if args.action == "messages":
        if args.target:
            open_chat(hwnd, args.target, exact=bool(args.exact), artifact_dir=args.artifact_dir)
            time.sleep(0.5)
        load_times = bounded_int(args.history_load_times, default=0, minimum=0, maximum=8)
        if load_times:
            scroll_chat_history(hwnd, load_times)
        return messages_payload(hwnd, probe, target=args.target or "", history_load_times=load_times, artifact_dir=args.artifact_dir)
    if args.action == "send":
        if not args.target:
            raise ValueError("--target is required for send")
        if args.text is None:
            raise ValueError("--text is required for send")
        opened = open_chat(hwnd, args.target, exact=bool(args.exact), artifact_dir=args.artifact_dir)
        time.sleep(0.4)
        if not opened:
            validation = validate_active_send_target(hwnd, args.target, exact=bool(args.exact), artifact_dir=args.artifact_dir)
            return {
                "ok": False,
                "online": True,
                "adapter": "win32_ocr",
                "state": "target_not_confirmed",
                "window_probe": probe,
                "target": args.target,
                "guard": validation,
                "error": "The target chat was not confirmed before sending.",
            }
        return send_payload(hwnd, probe, target=args.target, text=args.text, exact=bool(args.exact), artifact_dir=args.artifact_dir)
    return {"ok": False, "online": False, "adapter": "win32_ocr", "state": "unsupported_action"}


def status_payload(hwnd: int, probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="status")
    ocr_items = run_ocr(screenshot)
    login_like = any("登录" in item["text"] or "扫码" in item["text"] for item in ocr_items)
    return {
        "ok": not login_like,
        "online": not login_like,
        "adapter": "win32_ocr",
        "state": "main_window_compat",
        "window_probe": probe,
        "screenshot_path": path,
        "ocr_count": len(ocr_items),
        "compat_reason": "wxauto4_attach_fallback",
    }


def capabilities_payload(hwnd: int, probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="capabilities")
    ocr_items = run_ocr(screenshot)
    blocking_reason = blocking_screen_reason(ocr_items)
    online = blocking_reason != "login_or_qr"
    geometry = get_window_geometry(hwnd)
    geometry_check = validate_send_geometry(geometry)
    points = calculate_send_points(geometry) if geometry_check.get("ok") else geometry_check
    uia = inspect_uia_send_capability(hwnd, geometry) if geometry_check.get("ok") else {
        "ok": False,
        "reason": "geometry_unavailable_for_uia",
        "geometry": geometry,
    }
    receive = {
        "ok": bool(online and not blocking_reason),
        "method": "win32.screenshot+rapidocr",
        "blocked_by": blocking_reason,
    }
    guarded_click = {
        "ok": bool(online and not blocking_reason and geometry_check.get("ok") and points.get("ok")),
        "method": "win32.human_click_input+clipboard_paste+human_click_send",
        "geometry": geometry_check,
        "points": points,
        "rate_guard": {
            "enabled": env_flag("WECHAT_WIN32_OCR_SEND_RATE_GUARD", default=True),
            "min_interval_seconds": env_int("WECHAT_WIN32_OCR_SEND_MIN_INTERVAL_SECONDS", DEFAULT_SEND_MIN_INTERVAL_SECONDS),
            "burst_window_seconds": env_int("WECHAT_WIN32_OCR_SEND_BURST_WINDOW_SECONDS", DEFAULT_SEND_BURST_WINDOW_SECONDS),
            "burst_limit": env_int("WECHAT_WIN32_OCR_SEND_BURST_LIMIT", DEFAULT_SEND_BURST_LIMIT),
        },
    }
    if not online:
        scheme = "wechat_not_online"
    elif blocking_reason:
        scheme = "win32_ocr_blocked"
    elif uia.get("ok"):
        scheme = "win32_ocr_uia"
    elif guarded_click.get("ok"):
        scheme = "win32_ocr_guarded_click"
    elif receive.get("ok"):
        scheme = "win32_ocr_receive_only"
    else:
        scheme = "win32_ocr_unavailable"
    send_ok = bool(uia.get("ok") or guarded_click.get("ok"))
    return {
        "ok": bool(online and receive.get("ok")),
        "online": bool(online),
        "adapter": "win32_ocr",
        "scheme": scheme,
        "state": "capabilities_ocr",
        "window_probe": probe,
        "screenshot_path": path,
        "ocr_count": len(ocr_items),
        "blocking_reason": blocking_reason,
        "receive": receive,
        "send": {
            "ok": send_ok,
            "preferred_mode": "uia" if uia.get("ok") else ("guarded_human_click" if guarded_click.get("ok") else ""),
            "uia": uia,
            "guarded_click": guarded_click,
        },
        "compat_reason": "wxauto4_attach_fallback",
    }


def sessions_payload(hwnd: int, probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="sessions")
    items = run_ocr(screenshot)
    sessions = parse_sessions_from_ocr(items, screenshot.size)
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
        "state": "sessions_ocr",
        "window_probe": probe,
        "screenshot_path": path,
        "sessions": [
            {
                "name": item["name"],
                "title": item["name"],
                "content": item.get("preview", ""),
                "time": item.get("time", ""),
                "conversation_type": infer_conversation_type(item["name"]),
                "source_adapter": "win32_ocr",
                "ocr_confidence": item.get("confidence"),
            }
            for item in sessions
        ],
        "ocr_items_count": len(items),
    }


def messages_payload(
    hwnd: int,
    probe: dict[str, Any],
    *,
    target: str,
    history_load_times: int,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="messages")
    ocr_items = run_ocr(screenshot)
    messages = parse_messages_from_ocr(ocr_items, screenshot.size, target=target)
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
        "state": "messages_ocr",
        "window_probe": probe,
        "screenshot_path": path,
        "chat_info": {"chat_name": target, "source_adapter": "win32_ocr"},
        "history_load": {
            "ok": True,
            "requested_load_times": history_load_times,
            "mechanism": "win32_ocr.WheelUp+ScreenshotOCR",
        },
        "messages": messages,
        "ocr_items_count": len(ocr_items),
    }


def send_payload(
    hwnd: int,
    probe: dict[str, Any],
    *,
    target: str,
    text: str,
    exact: bool,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
    if not validation.get("ok"):
        return {
            "ok": False,
            "online": validation.get("online", True),
            "adapter": "win32_ocr",
            "state": "send_guard_blocked",
            "window_probe": probe,
            "target": target,
            "guard": validation,
            "error": str(validation.get("error") or validation.get("reason") or "send guard blocked"),
        }

    geometry = validation["geometry"]
    points = calculate_send_points(geometry)
    if not points.get("ok"):
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "send_geometry_blocked",
            "window_probe": probe,
            "target": target,
            "guard": {**validation, "points": points},
            "error": str(points.get("error") or "send points were unsafe"),
        }
    send_mode = str(os.getenv("WECHAT_WIN32_OCR_SEND_MODE") or DEFAULT_SEND_MODE).strip().lower()
    rate = reserve_send_rate(target=target, text=text)
    if not rate.get("ok"):
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "send_rate_limited",
            "window_probe": probe,
            "target": target,
            "guard": {**validation, "points": points, "rate": rate},
            "error": str(rate.get("error") or "win32_ocr fallback send is rate limited"),
        }
    uia_result = {"ok": False, "reason": "not_attempted", "mode": send_mode}
    click_result: dict[str, Any] = {"ok": False, "reason": "not_attempted", "mode": send_mode}
    if send_mode in {"uia_first", "uia_only"}:
        uia_result = send_with_uia_controls(hwnd, text, geometry=geometry)
    if not uia_result.get("ok"):
        if send_mode == "uia_only":
            return {
                "ok": False,
                "online": True,
                "adapter": "win32_ocr",
                "state": "send_uia_unavailable",
                "window_probe": probe,
                "target": target,
                "guard": {**validation, "points": points, "rate": rate, "uia": uia_result},
                "error": str(uia_result.get("error") or "UIA controls are unavailable for safe send."),
            }
        click_result = send_with_guarded_clicks(hwnd, text, points=points)
    time.sleep(0.5)
    post_validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
    active_result = uia_result if uia_result.get("ok") else click_result
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
        "state": "send_win32_clipboard",
        "window_probe": probe,
        "target": target,
        "send_result": {
            "ok": True,
            "method": active_result.get("method") or "win32.click_input+clipboard_paste+click_send",
            "mode": send_mode,
            "geometry": geometry,
            "input_point": points["input_point"],
            "send_point": points["send_point"],
            "rate": rate,
            "uia": uia_result,
            "click": click_result,
            "post_send_guard": post_validation,
        },
    }


def send_with_guarded_clicks(hwnd: int, text: str, *, points: dict[str, Any]) -> dict[str, Any]:
    # WeChat 4.1.x keeps the attachment toolbar near the bottom. Click safely in
    # the text area above it, then click the explicit send button.
    input_x = int(points["input_point"][0])
    input_y = int(points["input_point"][1])
    send_x = int(points["send_point"][0])
    send_y = int(points["send_point"][1])
    human_client_click(hwnd, input_x, input_y)
    time.sleep(random.uniform(0.15, 0.35))
    clipboard_copy(text)
    hotkey(win32con.VK_CONTROL, ord("V"))
    time.sleep(random.uniform(0.45, 0.9))
    human_client_click(hwnd, send_x, send_y)
    return {
        "ok": True,
        "method": "win32.human_click_input+clipboard_paste+human_click_send",
        "input_point": [input_x, input_y],
        "send_point": [send_x, send_y],
    }


def send_with_uia_controls(hwnd: int, text: str, *, geometry: dict[str, Any]) -> dict[str, Any]:
    try:
        import uiautomation as auto  # type: ignore
    except Exception as exc:
        return {"ok": False, "reason": "uiautomation_unavailable", "error": repr(exc)}

    try:
        root = auto.ControlFromHandle(hwnd)
        controls = collect_uia_controls(root, max_depth=8, max_count=900)
        edit = select_uia_edit_control(controls, geometry)
        send_button = select_uia_send_button(controls, geometry)
        if edit is None:
            return {"ok": False, "reason": "uia_edit_not_found", "control_count": len(controls)}
        if send_button is None:
            return {"ok": False, "reason": "uia_send_button_not_found", "control_count": len(controls)}

        edit.SetFocus()
        time.sleep(0.1)
        pattern_result = set_uia_control_value(auto, edit, text)
        if not pattern_result.get("ok"):
            return {**pattern_result, "control_count": len(controls)}
        time.sleep(0.15)
        invoke_result = invoke_uia_button(auto, send_button)
        if not invoke_result.get("ok"):
            return {**invoke_result, "control_count": len(controls)}
        return {
            "ok": True,
            "method": "uia.ValuePattern.SetValue+InvokePattern.Invoke",
            "control_count": len(controls),
            "edit": describe_uia_control(edit, geometry),
            "send_button": describe_uia_control(send_button, geometry),
        }
    except Exception as exc:
        return {"ok": False, "reason": "uia_send_failed", "error": repr(exc)}


def inspect_uia_send_capability(hwnd: int, geometry: dict[str, Any]) -> dict[str, Any]:
    try:
        import uiautomation as auto  # type: ignore
    except Exception as exc:
        return {"ok": False, "reason": "uiautomation_unavailable", "error": repr(exc)}

    try:
        root = auto.ControlFromHandle(hwnd)
        controls = collect_uia_controls(root, max_depth=8, max_count=900)
        edit = select_uia_edit_control(controls, geometry)
        send_button = select_uia_send_button(controls, geometry)
        missing: list[str] = []
        if edit is None:
            missing.append("edit")
        if send_button is None:
            missing.append("send_button")
        return {
            "ok": not missing,
            "reason": "uia_controls_ready" if not missing else "uia_controls_missing",
            "missing": missing,
            "control_count": len(controls),
            "edit": describe_uia_control(edit, geometry) if edit is not None else None,
            "send_button": describe_uia_control(send_button, geometry) if send_button is not None else None,
        }
    except Exception as exc:
        return {"ok": False, "reason": "uia_inspect_failed", "error": repr(exc)}


def collect_uia_controls(root: Any, *, max_depth: int, max_count: int) -> list[Any]:
    controls: list[Any] = []
    queue: list[tuple[Any, int]] = [(root, 0)]
    while queue and len(controls) < max_count:
        control, depth = queue.pop(0)
        if depth:
            controls.append(control)
        if depth >= max_depth:
            continue
        try:
            children = list(control.GetChildren())
        except Exception:
            children = []
        for child in children:
            if len(controls) + len(queue) >= max_count:
                break
            queue.append((child, depth + 1))
    return controls


def select_uia_edit_control(controls: list[Any], geometry: dict[str, Any]) -> Any | None:
    candidates: list[tuple[float, Any]] = []
    for control in controls:
        if "edit" not in str(safe_uia_attr(control, "ControlTypeName")).lower():
            continue
        rect = uia_rect_to_dict(safe_uia_attr(control, "BoundingRectangle"))
        if not rect_in_input_area(rect, geometry):
            continue
        rel = relative_rect(rect, geometry)
        area = max(1, rel["width"]) * max(1, rel["height"])
        score = area + rel["bottom"] * 2
        candidates.append((score, control))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def select_uia_send_button(controls: list[Any], geometry: dict[str, Any]) -> Any | None:
    candidates: list[tuple[float, Any]] = []
    for control in controls:
        control_type = str(safe_uia_attr(control, "ControlTypeName")).lower()
        name = normalize_ocr_text(safe_uia_attr(control, "Name"))
        if "button" not in control_type:
            continue
        if "发送" not in name and name.lower() not in {"send"}:
            continue
        rect = uia_rect_to_dict(safe_uia_attr(control, "BoundingRectangle"))
        if not rect_in_input_toolbar(rect, geometry):
            continue
        rel = relative_rect(rect, geometry)
        score = rel["right"] + rel["bottom"] * 2
        candidates.append((score, control))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def set_uia_control_value(auto: Any, control: Any, text: str) -> dict[str, Any]:
    try:
        pattern = control.GetPattern(auto.PatternId.ValuePattern)
        pattern.SetValue("")
        time.sleep(0.05)
        pattern.SetValue(text)
        return {"ok": True, "method": "ValuePattern.SetValue"}
    except Exception as exc:
        return {"ok": False, "reason": "uia_value_pattern_failed", "error": repr(exc)}


def invoke_uia_button(auto: Any, control: Any) -> dict[str, Any]:
    try:
        pattern = control.GetPattern(auto.PatternId.InvokePattern)
        pattern.Invoke()
        return {"ok": True, "method": "InvokePattern.Invoke"}
    except Exception:
        try:
            control.Click()
            return {"ok": True, "method": "Control.Click"}
        except Exception as exc:
            return {"ok": False, "reason": "uia_invoke_failed", "error": repr(exc)}


def describe_uia_control(control: Any, geometry: dict[str, Any]) -> dict[str, Any]:
    rect = uia_rect_to_dict(safe_uia_attr(control, "BoundingRectangle"))
    return {
        "name": normalize_ocr_text(safe_uia_attr(control, "Name")),
        "control_type": str(safe_uia_attr(control, "ControlTypeName") or ""),
        "class_name": str(safe_uia_attr(control, "ClassName") or ""),
        "rect": relative_rect(rect, geometry),
    }


def safe_uia_attr(control: Any, name: str) -> Any:
    try:
        value = getattr(control, name)
        return value() if callable(value) and name in {"Name", "ClassName", "ControlTypeName"} else value
    except Exception:
        return ""


def uia_rect_to_dict(rect: Any) -> dict[str, int]:
    return {
        "left": int(getattr(rect, "left", getattr(rect, "Left", 0)) or 0),
        "top": int(getattr(rect, "top", getattr(rect, "Top", 0)) or 0),
        "right": int(getattr(rect, "right", getattr(rect, "Right", 0)) or 0),
        "bottom": int(getattr(rect, "bottom", getattr(rect, "Bottom", 0)) or 0),
    }


def relative_rect(rect: dict[str, int], geometry: dict[str, Any]) -> dict[str, int]:
    left = int(rect.get("left") or 0) - int(geometry.get("left") or 0)
    top = int(rect.get("top") or 0) - int(geometry.get("top") or 0)
    right = int(rect.get("right") or 0) - int(geometry.get("left") or 0)
    bottom = int(rect.get("bottom") or 0) - int(geometry.get("top") or 0)
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }


def rect_in_input_area(rect: dict[str, int], geometry: dict[str, Any]) -> bool:
    rel = relative_rect(rect, geometry)
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if rel["width"] <= 80 or rel["height"] <= 30:
        return False
    if rel["right"] <= session_split_x(width) + 100:
        return False
    return rel["top"] >= int(height * 0.70) and rel["bottom"] <= height + 8


def rect_in_input_toolbar(rect: dict[str, int], geometry: dict[str, Any]) -> bool:
    rel = relative_rect(rect, geometry)
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if rel["width"] <= 20 or rel["height"] <= 15:
        return False
    if rel["right"] <= session_split_x(width) + 60:
        return False
    return rel["top"] >= int(height * 0.78) and rel["bottom"] <= height + 8


def open_chat(hwnd: int, target: str, *, exact: bool, artifact_dir: str | None = None) -> bool:
    screenshot, _path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="open_chat")
    ocr_items = run_ocr(screenshot)
    if active_chat_matches(ocr_items, screenshot.size, target=target, exact=exact):
        return True
    sessions = parse_sessions_from_ocr(ocr_items, screenshot.size)
    for item in sessions:
        name = item["name"]
        matched = name == target if exact else (target in name or name in target)
        if matched and item.get("center_y") is not None:
            client_click(hwnd, SESSION_CLICK_X, int(item["center_y"]))
            time.sleep(0.4)
            return validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir).get("ok") is True

    client_click(hwnd, SEARCH_BOX_REL[0], SEARCH_BOX_REL[1])
    time.sleep(0.1)
    hotkey(win32con.VK_CONTROL, ord("A"))
    clipboard_copy(target)
    hotkey(win32con.VK_CONTROL, ord("V"))
    time.sleep(0.5)
    key_press(win32con.VK_RETURN)
    time.sleep(0.8)
    return validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir).get("ok") is True


def validate_active_send_target(
    hwnd: int,
    target: str,
    *,
    exact: bool,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    geometry = get_window_geometry(hwnd)
    geometry_check = validate_send_geometry(geometry)
    if not geometry_check.get("ok"):
        return {**geometry_check, "online": True, "geometry": geometry}
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="send_guard")
    ocr_items = run_ocr(screenshot)
    blocking_reason = blocking_screen_reason(ocr_items)
    if blocking_reason:
        return {
            "ok": False,
            "online": False if blocking_reason in {"login_or_qr"} else True,
            "reason": blocking_reason,
            "geometry": geometry,
            "screenshot_path": path,
            "error": f"WeChat send guard found blocking screen: {blocking_reason}",
        }
    if not active_chat_matches(ocr_items, screenshot.size, target=target, exact=exact):
        return {
            "ok": False,
            "online": True,
            "reason": "target_title_not_confirmed",
            "geometry": geometry,
            "screenshot_path": path,
            "error": "The active chat title did not match the requested target.",
        }
    return {
        "ok": True,
        "online": True,
        "reason": "target_confirmed",
        "geometry": geometry,
        "screenshot_path": path,
    }


def get_window_geometry(hwnd: int) -> dict[str, int]:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right),
        "bottom": int(bottom),
        "width": int(right - left),
        "height": int(bottom - top),
    }


def validate_send_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width < MIN_SEND_CLIENT_WIDTH or height < MIN_SEND_CLIENT_HEIGHT:
        return {
            "ok": False,
            "reason": "window_too_small_for_safe_send",
            "geometry": geometry,
            "error": f"WeChat window is too small for safe send: {width}x{height}.",
        }
    return {"ok": True, "reason": "geometry_ok", "geometry": geometry}


def calculate_send_points(geometry: dict[str, Any]) -> dict[str, Any]:
    geometry_check = validate_send_geometry(geometry)
    if not geometry_check.get("ok"):
        return geometry_check
    client_width = int(geometry["width"])
    client_height = int(geometry["height"])
    input_x = int(client_width * 0.65)
    input_y = client_height - 145
    send_x = client_width - 62
    send_y = client_height - 44
    if input_y < client_height * 0.72 or send_y < client_height * 0.82:
        return {
            "ok": False,
            "reason": "send_points_outside_input_area",
            "geometry": geometry,
            "error": "Calculated send points are outside the expected input area.",
        }
    if input_x <= session_split_x(client_width) or send_x <= session_split_x(client_width):
        return {
            "ok": False,
            "reason": "send_points_inside_session_list",
            "geometry": geometry,
            "error": "Calculated send points overlap the session list.",
        }
    return {"ok": True, "input_point": [input_x, input_y], "send_point": [send_x, send_y], "geometry": geometry}


def blocking_screen_reason(ocr_items: list[dict[str, Any]]) -> str:
    texts = [normalize_ocr_text(item.get("text")) for item in ocr_items if normalize_ocr_text(item.get("text"))]
    joined = "\n".join(texts)
    if any(token in joined for token in ("登录", "扫码")):
        return "login_or_qr"
    for token in BLOCKING_SCREEN_TOKENS:
        if token in joined:
            return f"blocking_text:{token}"
    return ""


def reserve_send_rate(*, target: str, text: str) -> dict[str, Any]:
    if env_flag("WECHAT_WIN32_OCR_SEND_RATE_GUARD", default=True) is False:
        return {"ok": True, "guard_disabled": True}
    now_ts = time.time()
    min_interval = env_int("WECHAT_WIN32_OCR_SEND_MIN_INTERVAL_SECONDS", DEFAULT_SEND_MIN_INTERVAL_SECONDS)
    burst_window = env_int("WECHAT_WIN32_OCR_SEND_BURST_WINDOW_SECONDS", DEFAULT_SEND_BURST_WINDOW_SECONDS)
    burst_limit = env_int("WECHAT_WIN32_OCR_SEND_BURST_LIMIT", DEFAULT_SEND_BURST_LIMIT)
    state = read_send_guard_state()
    decision = send_rate_decision(
        state,
        target=target,
        now_ts=now_ts,
        min_interval_seconds=min_interval,
        burst_window_seconds=burst_window,
        burst_limit=burst_limit,
    )
    if not decision.get("ok"):
        return decision
    events = [
        item
        for item in state.get("events", [])
        if isinstance(item, dict) and now_ts - float(item.get("at") or 0) <= max(burst_window, min_interval, 1)
    ]
    events.append(
        {
            "target": target,
            "at": now_ts,
            "text_hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
        }
    )
    write_send_guard_state({"events": events, "updated_at": now_ts})
    return decision


def send_rate_decision(
    state: dict[str, Any],
    *,
    target: str,
    now_ts: float,
    min_interval_seconds: int,
    burst_window_seconds: int,
    burst_limit: int,
) -> dict[str, Any]:
    events = [item for item in state.get("events", []) if isinstance(item, dict)]
    target_events = [item for item in events if str(item.get("target") or "") == target]
    if min_interval_seconds > 0 and target_events:
        last_at = max(float(item.get("at") or 0) for item in target_events)
        elapsed = now_ts - last_at
        if elapsed < min_interval_seconds:
            return {
                "ok": False,
                "reason": "min_interval_not_elapsed",
                "min_interval_seconds": min_interval_seconds,
                "wait_seconds": round(min_interval_seconds - elapsed, 2),
                "error": "win32_ocr fallback send is too frequent for this target.",
            }
    if burst_window_seconds > 0 and burst_limit > 0:
        recent = [
            item
            for item in target_events
            if now_ts - float(item.get("at") or 0) <= burst_window_seconds
        ]
        if len(recent) >= burst_limit:
            oldest = min(float(item.get("at") or 0) for item in recent)
            return {
                "ok": False,
                "reason": "burst_limit_reached",
                "burst_limit": burst_limit,
                "burst_window_seconds": burst_window_seconds,
                "wait_seconds": round(max(0.0, burst_window_seconds - (now_ts - oldest)), 2),
                "error": "win32_ocr fallback send burst limit reached.",
            }
    return {
        "ok": True,
        "reason": "rate_ok",
        "min_interval_seconds": min_interval_seconds,
        "burst_window_seconds": burst_window_seconds,
        "burst_limit": burst_limit,
    }


def read_send_guard_state() -> dict[str, Any]:
    try:
        payload = json.loads(SEND_GUARD_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"events": []}
    return payload if isinstance(payload, dict) else {"events": []}


def write_send_guard_state(payload: dict[str, Any]) -> None:
    SEND_GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = SEND_GUARD_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, SEND_GUARD_PATH)


def env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def active_chat_matches(ocr_items: list[dict[str, Any]], image_size: tuple[int, int], *, target: str, exact: bool) -> bool:
    if not target:
        return False
    width, _height = image_size
    split_x = session_split_x(width)
    for item in ocr_items:
        text = normalize_ocr_text(item.get("text"))
        if not text:
            continue
        if item["center_y"] > CHAT_HEADER_MAX_Y or item["right"] < split_x:
            continue
        candidates = {text, re.sub(r"\(\d+\)$", "", text).strip(), re.sub(r"（\d+）$", "", text).strip()}
        if exact and target in candidates:
            return True
        if not exact and any(target in candidate or candidate in target for candidate in candidates if candidate):
            return True
    return False


def scroll_chat_history(hwnd: int, load_times: int) -> None:
    rect = win32gui.GetWindowRect(hwnd)
    x = max(380, int((rect[2] - rect[0]) * 0.6))
    y = max(180, int((rect[3] - rect[1]) * 0.45))
    client_click(hwnd, x, y)
    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))
    win32api.SetCursorPos((screen_x, screen_y))
    for _ in range(max(0, load_times)):
        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, 6 * 120, 0)
        time.sleep(0.2)


def capture_wechat(hwnd: int, *, artifact_dir: str | None = None, label: str = "wechat") -> tuple[Any, str]:
    rect = win32gui.GetWindowRect(hwnd)
    image = ImageGrab.grab(bbox=rect)
    saved = ""
    if artifact_dir:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        saved_path = root / f"{label}_{int(time.time() * 1000)}.png"
        image.save(saved_path)
        saved = str(saved_path)
    return image, saved


def run_ocr(image: Any) -> list[dict[str, Any]]:
    global _OCR_ENGINE
    if RapidOCR is None:
        raise RuntimeError(f"rapidocr_onnxruntime_unavailable: {_OCR_IMPORT_ERROR}")
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    result, _ = _OCR_ENGINE(image)
    items: list[dict[str, Any]] = []
    for row in result or []:
        try:
            box, text, confidence = row
        except ValueError:
            continue
        clean = normalize_ocr_text(text)
        if not clean:
            continue
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < OCR_MIN_CONFIDENCE:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append(
            {
                "text": clean,
                "confidence": conf,
                "box": box,
                "left": min(xs),
                "right": max(xs),
                "top": min(ys),
                "bottom": max(ys),
                "center_x": sum(xs) / len(xs),
                "center_y": sum(ys) / len(ys),
            }
        )
    items.sort(key=lambda item: (float(item["top"]), float(item["left"])))
    return items


def parse_sessions_from_ocr(ocr_items: list[dict[str, Any]], image_size: tuple[int, int]) -> list[dict[str, Any]]:
    width, height = image_size
    split_x = session_split_x(width)
    candidates: list[dict[str, Any]] = []
    for item in ocr_items:
        text = str(item.get("text") or "").strip()
        if not is_session_name_candidate(text):
            continue
        if item["center_y"] < 90 or item["center_y"] > height - 20:
            continue
        if item["left"] < 58 or item["left"] > split_x - 45:
            continue
        if item["right"] > split_x + 20:
            continue
        candidates.append(item)

    sessions: list[dict[str, Any]] = []
    last_y = -999.0
    for item in sorted(candidates, key=lambda row: float(row["center_y"])):
        center_y = float(item["center_y"])
        if center_y - last_y < 44:
            continue
        name = normalize_session_name(str(item.get("text") or ""))
        if not name or any(existing["name"] == name for existing in sessions):
            continue
        sessions.append(
            {
                "name": name,
                "confidence": item.get("confidence"),
                "center_y": center_y,
                "source_adapter": "win32_ocr",
            }
        )
        last_y = center_y
    return sessions


def parse_messages_from_ocr(ocr_items: list[dict[str, Any]], image_size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
    width, height = image_size
    split_x = session_split_x(width)
    bottom_exclude_px = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_MESSAGE_BOTTOM_EXCLUDE_PX"),
        default=DEFAULT_MESSAGE_BOTTOM_EXCLUDE_PX,
        minimum=60,
        maximum=180,
    )
    rows: list[dict[str, Any]] = []
    for item in ocr_items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if item["center_y"] < CHAT_HEADER_MAX_Y:
            continue
        if item["center_y"] > height - bottom_exclude_px:
            continue
        if item["left"] < split_x - 5:
            continue
        if is_message_noise(text):
            continue
        rows.append(item)

    grouped: list[list[dict[str, Any]]] = []
    for item in sorted(rows, key=lambda row: (float(row["center_y"]), float(row["left"]))):
        side = "self" if float(item["center_x"]) > width * 0.68 else "unknown"
        if not grouped:
            grouped.append([{**item, "side": side}])
            continue
        previous = grouped[-1][-1]
        previous_side = str(previous.get("side") or "unknown")
        vertical_gap = float(item["top"]) - float(previous["bottom"])
        if previous_side == side and vertical_gap <= 28:
            grouped[-1].append({**item, "side": side})
        else:
            grouped.append([{**item, "side": side}])

    messages: list[dict[str, Any]] = []
    for group in grouped:
        content = "\n".join(str(item.get("text") or "").strip() for item in group if str(item.get("text") or "").strip())
        content = normalize_message_content(content)
        if not content:
            continue
        side = str(group[0].get("side") or "unknown")
        y = float(group[0].get("center_y") or 0)
        digest = hashlib.sha1(f"{target}|{side}|{round(y)}|{content}".encode("utf-8")).hexdigest()[:16]
        messages.append(
            {
                "id": f"win32_ocr:{digest}",
                "type": "text",
                "sender": "self" if side == "self" else "unknown",
                "sender_role": "self" if side == "self" else "unknown",
                "content": content,
                "time": "",
                "source_adapter": "win32_ocr",
                "ocr_confidence": min(float(item.get("confidence") or 0) for item in group),
            }
        )
    return messages


def probe_wechat_windows() -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    visible_windows: list[dict[str, Any]] = []
    main_windows: list[dict[str, Any]] = []
    visible_main_windows: list[dict[str, Any]] = []
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    process_query_limited_information = 0x1000

    def process_path(pid: int) -> str:
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def callback(hwnd: int, _lparam: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = process_path(int(pid.value))
        if not path.lower().endswith("\\weixin.exe"):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        item = {
            "hwnd": int(hwnd),
            "pid": int(pid.value),
            "title": title_buffer.value,
            "class_name": class_buffer.value,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "path": path,
        }
        windows.append(item)
        if item["visible"]:
            visible_windows.append(item)
        if is_wechat_main_window(item):
            main_windows.append(item)
            if item["visible"]:
                visible_main_windows.append(item)
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return {
        "windows": windows,
        "visible_windows": visible_windows,
        "main_windows": main_windows,
        "visible_main_windows": visible_main_windows,
        "visible_count": len(visible_windows),
        "main_count": len(main_windows),
        "visible_main_count": len(visible_main_windows),
    }


def ensure_visible_wechat_window() -> dict[str, Any]:
    probe = probe_wechat_windows()
    if probe["visible_main_windows"]:
        focused = focus_wechat_window(probe)
        if focused:
            time.sleep(0.2)
            probe = probe_wechat_windows()
            probe["focused_window"] = focused
        return probe
    restored = restore_wechat_window(probe)
    if restored:
        time.sleep(0.8)
        probe = probe_wechat_windows()
        probe["restored_window"] = restored
        focused = focus_wechat_window(probe)
        if focused:
            time.sleep(0.2)
            probe = probe_wechat_windows()
            probe["focused_window"] = focused
    return probe


def restore_wechat_window(probe: dict[str, Any]) -> dict[str, Any] | None:
    for item in probe.get("windows") or []:
        if not is_wechat_main_window(item):
            continue
        hwnd = int(item.get("hwnd") or 0)
        if hwnd:
            activate_window(hwnd)
            return dict(item)
    return None


def focus_wechat_window(probe: dict[str, Any]) -> dict[str, Any] | None:
    visible = probe.get("visible_main_windows") or []
    if not visible:
        return None
    item = visible[0]
    hwnd = int(item.get("hwnd") or 0)
    if hwnd:
        activate_window(hwnd)
        return dict(item)
    return None


def activate_window(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.ShowWindow(hwnd, 5)
    user32.BringWindowToTop(hwnd)
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def configure_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def client_click(hwnd: int, x: int, y: int) -> None:
    """Click a WeChat client coordinate without relying on global DPI math."""
    activate_window(hwnd)
    lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
    time.sleep(0.03)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    time.sleep(0.06)
    win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    time.sleep(0.1)


def human_client_click(hwnd: int, x: int, y: int) -> None:
    """Move the real cursor with small jitter before clicking a client point."""
    activate_window(hwnd)
    screen_x, screen_y = client_to_screen(hwnd, int(x), int(y))
    start_x, start_y = win32api.GetCursorPos()
    steps = random.randint(5, 9)
    for step in range(1, steps + 1):
        ratio = step / steps
        ease = ratio * ratio * (3 - 2 * ratio)
        jitter_x = random.randint(-2, 2) if step < steps else 0
        jitter_y = random.randint(-2, 2) if step < steps else 0
        next_x = int(start_x + (screen_x - start_x) * ease) + jitter_x
        next_y = int(start_y + (screen_y - start_y) * ease) + jitter_y
        win32api.SetCursorPos((next_x, next_y))
        time.sleep(random.uniform(0.015, 0.045))
    time.sleep(random.uniform(0.04, 0.12))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(random.uniform(0.05, 0.12))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(random.uniform(0.12, 0.28))


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(int(x), int(y))
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point))
    return int(point.x), int(point.y)


def click(x: int, y: int) -> None:
    win32api.SetCursorPos((int(x), int(y)))
    time.sleep(0.03)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.03)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def hotkey(modifier: int, key: int) -> None:
    win32api.keybd_event(modifier, 0, 0, 0)
    time.sleep(0.02)
    win32api.keybd_event(key, 0, 0, 0)
    time.sleep(0.02)
    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(modifier, 0, win32con.KEYEVENTF_KEYUP, 0)


def key_press(key: int) -> None:
    win32api.keybd_event(key, 0, 0, 0)
    time.sleep(0.03)
    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)


def is_wechat_main_window(item: dict[str, Any]) -> bool:
    title = normalize_wechat_title(str(item.get("title") or ""))
    class_name = str(item.get("class_name") or "").lower()
    if not title:
        return False
    if "qwindowicon" not in class_name and "wechatmainwndforpc" not in class_name:
        return False
    lowered = title.lower()
    if any(token in lowered for token in ("login", "qr", "update")) or any(token in title for token in ("登录", "扫码", "更新")):
        return False
    return any(token in title for token in ("微信", "Weixin", "WeChat")) or any(token in lowered for token in ("weixin", "wechat"))


def normalize_wechat_title(title: str) -> str:
    text = str(title or "").strip()
    text = re.sub(r"^\(\d+\)\s*", "", text).strip()
    text = re.sub(r"^（\d+）\s*", "", text).strip()
    return text


def normalize_ocr_text(text: Any) -> str:
    clean = str(text or "").replace("\u3000", " ").strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean


def normalize_session_name(text: str) -> str:
    clean = normalize_ocr_text(text)
    clean = re.sub(r"^[：:.\s]+", "", clean).strip()
    return clean


def normalize_message_content(text: str) -> str:
    return str(text or "").strip()


def session_split_x(width: int) -> int:
    return max(300, min(370, int(width * 0.52)))


def is_session_name_candidate(text: str) -> bool:
    if not text:
        return False
    if len(text) > 28:
        return False
    if text.startswith("["):
        return False
    if "搜索" in text or text in {"?", "？", "+", "..."}:
        return False
    if re.fullmatch(r"(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}|星期.|(今天|昨天|前天)\s*\d{1,2}:\d{2})", text):
        return False
    if "..." in text or "…" in text:
        return False
    return True


def is_message_noise(text: str) -> bool:
    if re.fullmatch(r"(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}|星期.\s*\d{1,2}:\d{2}|星期.)", text):
        return True
    if text in {"发送", "按住 Alt 说话"}:
        return True
    return False


def infer_conversation_type(name: str) -> str:
    if name in {"文件传输助手", "File Transfer"}:
        return "file_transfer"
    if re.search(r"(群|群聊|测试|chatroom|room)", name, re.IGNORECASE):
        return "group"
    return "private"


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


if __name__ == "__main__":
    raise SystemExit(main())
