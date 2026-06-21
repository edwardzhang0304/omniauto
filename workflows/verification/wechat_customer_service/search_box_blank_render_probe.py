from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar as sidecar  # noqa: E402


ARTIFACT_ROOT = (
    PROJECT_ROOT
    / "runtime"
    / "apps"
    / "wechat_ai_customer_service"
    / "test_artifacts"
    / "search_box_blank_render_probe"
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def compact_probe(probe: dict[str, Any]) -> dict[str, Any]:
    selected = probe.get("selected_main_window") if isinstance(probe.get("selected_main_window"), dict) else {}
    return {
        "visible_count": probe.get("visible_count"),
        "main_count": probe.get("main_count"),
        "visible_main_count": probe.get("visible_main_count"),
        "selected_main_window": {
            "hwnd": selected.get("hwnd"),
            "pid": selected.get("pid"),
            "title": selected.get("title"),
            "class_name": selected.get("class_name"),
            "visible": selected.get("visible"),
            "path": selected.get("path"),
        },
    }


def snapshot(
    *,
    hwnd: int,
    geometry: dict[str, Any],
    artifact_dir: Path,
    label: str,
) -> dict[str, Any]:
    screenshot, screenshot_path = sidecar.capture_wechat(hwnd, artifact_dir=str(artifact_dir), label=label)
    ocr_items = sidecar.run_ocr(screenshot)
    blank = sidecar.detect_blank_render(screenshot, ocr_items, geometry=geometry)
    sessions = sidecar.parse_sessions_from_ocr(ocr_items, screenshot.size, screenshot=screenshot)
    surface = sidecar.target_switch_surface_state(
        screenshot,
        ocr_items,
        geometry=geometry,
        screenshot_path=screenshot_path,
        target="文件传输助手",
    )
    return {
        "label": label,
        "created_at": now_text(),
        "screenshot_path": screenshot_path,
        "image_size": list(screenshot.size),
        "ocr_count": len(ocr_items),
        "ocr_texts": [str(item.get("text") or "") for item in ocr_items[:24]],
        "blank_render": blank,
        "surface_state": surface,
        "sessions": [
            {
                "name": item.get("name"),
                "content": item.get("content"),
                "session_key": item.get("session_key"),
                "unread_signal": item.get("unread_signal"),
            }
            for item in sessions[:12]
        ],
    }


def search_box_bounds(geometry: dict[str, Any]) -> list[int]:
    width = int(geometry.get("width") or 0)
    return [66, 42, min(max(218, width // 4), max(90, width - 30)), 90]


def search_box_points(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    bounds = search_box_bounds(geometry)
    left, top, right, bottom = bounds
    center_x, center_y = sidecar.sidebar_search_input_focus_point_for_geometry(geometry)
    center_x, center_y = sidecar.clamp_point_to_bounds(int(center_x), int(center_y), bounds)
    return [
        {"name": "search_center", "x": center_x, "y": center_y, "bounds": bounds},
        {"name": "search_left_inner", "x": left + 22, "y": center_y, "bounds": bounds},
        {"name": "search_right_inner", "x": right - 22, "y": center_y, "bounds": bounds},
    ]


def stop_reason_from_snapshot(payload: dict[str, Any]) -> str:
    blank = payload.get("blank_render") if isinstance(payload.get("blank_render"), dict) else {}
    if blank.get("detected"):
        return "blank_render"
    surface = payload.get("surface_state") if isinstance(payload.get("surface_state"), dict) else {}
    state = str(surface.get("state") or "")
    reason = str(surface.get("reason") or "")
    if "blank" in state or "blank" in reason:
        return "blank_render"
    if state == "wrong_target_service_container_detected" or "service_container_wrong_target" in reason:
        return "service_container_wrong_target"
    return ""


def activate_and_wait(hwnd: int, *, timeout_seconds: float = 3.0) -> dict[str, Any]:
    started = time.monotonic()
    attempts = 0
    last_guard: dict[str, Any] = {}
    while time.monotonic() - started <= timeout_seconds:
        attempts += 1
        sidecar.activate_window(hwnd)
        time.sleep(0.25)
        last_guard = sidecar.foreground_window_matches_target(hwnd)
        if last_guard.get("ok"):
            return {"ok": True, "attempts": attempts, "guard": last_guard}
        time.sleep(0.25)
    return {"ok": False, "attempts": attempts, "guard": last_guard}


def query_visible_in_snapshot(snapshot_payload: dict[str, Any], query: str) -> dict[str, Any]:
    compact_query = "".join(ch for ch in str(query or "") if not ch.isspace())
    texts = [str(text or "") for text in snapshot_payload.get("ocr_texts") or []]
    compact_surface = "".join("".join(ch for ch in text if not ch.isspace()) for text in texts)
    sessions = snapshot_payload.get("sessions") if isinstance(snapshot_payload.get("sessions"), list) else []
    matched_sessions = [
        str(item.get("name") or "")
        for item in sessions
        if isinstance(item, dict) and compact_query and compact_query in "".join(ch for ch in str(item.get("name") or "") if not ch.isspace())
    ]
    return {
        "ok": bool(compact_query and (compact_query in compact_surface or matched_sessions)),
        "query": query,
        "matched_by": "ocr_text" if compact_query and compact_query in compact_surface else "session_name" if matched_sessions else "",
        "matched_sessions": matched_sessions,
    }


def clear_query_after_probe(
    hwnd: int,
    query: str,
    *,
    geometry: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    guard = sidecar.basic_send_window_guard(hwnd)
    if not guard.get("ok"):
        return {"ok": False, "reason": "window_guard_failed_before_query_cleanup", "window_guard": guard}
    key_count = 0
    # Do not use Ctrl+A or Escape in this diagnostic path. Backspace the known
    # probe query slowly so the operation remains reversible and non-mechanical.
    for index, _ch in enumerate(str(query or "")):
        sidecar.key_press(sidecar.win32con.VK_BACK)
        key_count += 1
        time.sleep(0.12 + (index % 3) * 0.05)
    time.sleep(0.8)
    dismiss_result = sidecar.dismiss_sidebar_search_state(
        hwnd,
        target_hint=query,
        geometry=geometry,
        artifact_dir=str(artifact_dir),
    )
    if not dismiss_result.get("ok"):
        return {
            "ok": False,
            "reason": str(dismiss_result.get("reason") or "search_dismiss_failed_after_query_cleanup"),
            "method": "slow_backspace_query_cleanup",
            "key_count": key_count,
            "dismiss_result": dismiss_result,
        }
    return {
        "ok": True,
        "method": "slow_backspace_query_cleanup",
        "key_count": key_count,
        "dismiss_result": dismiss_result,
    }


def run_probe(run_id: str, *, repeats: int, mode: str, settle_seconds: float, query: str) -> dict[str, Any]:
    run_dir = ARTIFACT_ROOT / run_id
    progress_path = run_dir / "progress.jsonl"
    result: dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "mode": mode,
        "repeats": repeats,
        "started_at": now_text(),
        "run_dir": str(run_dir),
        "events": [],
    }
    probe = sidecar.probe_wechat_windows()
    result["window_probe"] = compact_probe(probe)
    selected = sidecar.select_primary_visible_main_window(probe)
    if not selected:
        result["error"] = "wechat_main_window_not_found"
        write_json(run_dir / "result.json", result)
        return result
    hwnd = int(selected.get("hwnd") or 0)
    geometry = sidecar.get_window_geometry(hwnd)
    result["geometry"] = geometry
    geometry_check = sidecar.validate_capture_geometry(geometry)
    result["geometry_check"] = geometry_check
    if not geometry_check.get("ok"):
        result["error"] = "wechat_geometry_not_ready"
        write_json(run_dir / "result.json", result)
        return result

    baseline = snapshot(hwnd=hwnd, geometry=geometry, artifact_dir=run_dir, label="baseline")
    result["baseline"] = baseline
    append_jsonl(progress_path, {"event": "baseline", "snapshot": baseline})
    baseline_stop = stop_reason_from_snapshot(baseline)
    if baseline_stop:
        result["error"] = baseline_stop
        result["stopped_before_click"] = True
        write_json(run_dir / "result.json", result)
        return result

    points = search_box_points(geometry)
    for index in range(1, repeats + 1):
        point = points[(index - 1) % len(points)]
        event: dict[str, Any] = {
            "event": "probe_round",
            "round": index,
            "point": point,
            "started_at": now_text(),
        }
        if mode in {"activate", "search_click", "search_clear", "search_query"}:
            event["activation"] = activate_and_wait(hwnd)
            time.sleep(max(0.2, settle_seconds))
        before = snapshot(hwnd=hwnd, geometry=geometry, artifact_dir=run_dir, label=f"r{index:02d}_before")
        event["before"] = before
        before_stop = stop_reason_from_snapshot(before)
        if before_stop:
            event["error"] = before_stop
            event["stopped_before_action"] = True
            result["events"].append(event)
            append_jsonl(progress_path, event)
            result["error"] = before_stop
            write_json(run_dir / "result.json", result)
            return result
        if mode == "search_click":
            sidecar.human_window_image_click_in_bounds(
                hwnd,
                int(point["x"]),
                int(point["y"]),
                bounds=[int(value) for value in point["bounds"]],
                action_name="diagnostic_search_box_click",
            )
            time.sleep(max(0.3, settle_seconds))
        if mode == "search_clear":
            event["clear_result"] = sidecar.clear_sidebar_search_box_without_select_all(
                hwnd,
                int(point["x"]),
                int(point["y"]),
                target_hint="文件传输助手",
                geometry=geometry,
                artifact_dir=str(run_dir),
            )
            time.sleep(max(0.3, settle_seconds))
        if mode == "search_query":
            event["clear_result"] = sidecar.clear_sidebar_search_box_without_select_all(
                hwnd,
                int(point["x"]),
                int(point["y"]),
                target_hint=query,
                geometry=geometry,
                artifact_dir=str(run_dir),
            )
            if not event["clear_result"].get("ok"):
                event["error"] = str(event["clear_result"].get("reason") or "search_clear_failed")
                result["events"].append(event)
                append_jsonl(progress_path, event)
                result["error"] = event["error"]
                write_json(run_dir / "result.json", result)
                return result
            event["input_result"] = sidecar.type_sidebar_search_query(hwnd, query)
            if not event["input_result"].get("ok"):
                event["error"] = str(event["input_result"].get("reason") or "search_input_failed")
                result["events"].append(event)
                append_jsonl(progress_path, event)
                result["error"] = event["error"]
                write_json(run_dir / "result.json", result)
                return result
            time.sleep(max(1.1, settle_seconds))
            event["query_snapshot"] = snapshot(hwnd=hwnd, geometry=geometry, artifact_dir=run_dir, label=f"r{index:02d}_query")
            event["query_visible"] = query_visible_in_snapshot(event["query_snapshot"], query)
            query_stop = stop_reason_from_snapshot(event["query_snapshot"])
            if query_stop:
                event["error"] = query_stop
                result["events"].append(event)
                append_jsonl(progress_path, event)
                result["error"] = query_stop
                write_json(run_dir / "result.json", result)
                return result
            if not event["query_visible"].get("ok"):
                event["error"] = "query_not_visible_after_search_input"
                result["events"].append(event)
                append_jsonl(progress_path, event)
                result["error"] = event["error"]
                write_json(run_dir / "result.json", result)
                return result
            event["cleanup_result"] = clear_query_after_probe(
                hwnd,
                query,
                geometry=geometry,
                artifact_dir=run_dir,
            )
            if not event["cleanup_result"].get("ok"):
                event["error"] = str(event["cleanup_result"].get("reason") or "query_cleanup_failed")
                result["events"].append(event)
                append_jsonl(progress_path, event)
                result["error"] = event["error"]
                write_json(run_dir / "result.json", result)
                return result
            time.sleep(max(0.6, settle_seconds))
        after = snapshot(hwnd=hwnd, geometry=geometry, artifact_dir=run_dir, label=f"r{index:02d}_after")
        event["after"] = after
        after_stop = stop_reason_from_snapshot(after)
        if after_stop:
            event["error"] = after_stop
            event["stopped_after_action"] = True
            result["events"].append(event)
            append_jsonl(progress_path, event)
            result["error"] = after_stop
            write_json(run_dir / "result.json", result)
            return result
        result["events"].append(event)
        append_jsonl(progress_path, event)
        time.sleep(max(0.5, settle_seconds))

    result["ok"] = True
    result["finished_at"] = now_text()
    write_json(run_dir / "result.json", result)
    return result


def main() -> int:
    sidecar.configure_dpi_awareness()
    parser = argparse.ArgumentParser(description="Live diagnostic probe for WeChat search-box blank-render incidents.")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--mode", choices=["observe", "activate", "search_click", "search_clear", "search_query"], default="observe")
    parser.add_argument("--query", default="文件传输助手")
    parser.add_argument("--settle-seconds", type=float, default=1.2)
    args = parser.parse_args()
    result = run_probe(
        str(args.run_id),
        repeats=max(1, min(int(args.repeats), 12)),
        mode=str(args.mode),
        settle_seconds=float(args.settle_seconds),
        query=str(args.query or ""),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
