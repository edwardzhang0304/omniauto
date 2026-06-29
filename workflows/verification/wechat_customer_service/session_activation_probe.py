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
    / "session_activation_probe"
)


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def snapshot(hwnd: int, target: str, *, geometry: dict[str, Any], run_dir: Path, label: str) -> dict[str, Any]:
    shot, path = sidecar.capture_wechat(hwnd, artifact_dir=str(run_dir), label=label)
    items = sidecar.run_ocr(shot)
    return {
        "label": label,
        "created_at": now_text(),
        "screenshot_path": path,
        "ocr_count": len(items),
        "ocr_texts": [str(item.get("text") or "") for item in items[:24]],
        "blank_render": sidecar.detect_blank_render(shot, items, geometry=geometry),
        "active_match": bool(sidecar.active_chat_matches(items, shot.size, target=target, exact=True)),
        "sessions": [
            {
                "name": item.get("name"),
                "session_key": item.get("session_key"),
                "center_y": item.get("center_y"),
                "left": item.get("left"),
                "right": item.get("right"),
            }
            for item in sidecar.parse_sessions_from_ocr(items, shot.size, screenshot=shot)[:12]
        ],
    }


def find_session(sessions: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    for item in sessions:
        if sidecar.session_name_matches(str(item.get("name") or ""), target, exact=True):
            return item
    return None


def run_probe(run_id: str, target: str, mode: str) -> dict[str, Any]:
    run_dir = ARTIFACT_ROOT / run_id
    result: dict[str, Any] = {
        "ok": False,
        "run_id": run_id,
        "target": target,
        "mode": mode,
        "started_at": now_text(),
        "run_dir": str(run_dir),
    }
    probe = sidecar.probe_wechat_windows()
    selected = sidecar.select_primary_visible_main_window(probe)
    if not selected:
        result["error"] = "wechat_main_window_not_found"
        write_json(run_dir / "result.json", result)
        return result
    hwnd = int(selected.get("hwnd") or 0)
    sidecar.activate_window(hwnd)
    time.sleep(0.8)
    geometry = sidecar.get_window_geometry(hwnd)
    result["geometry"] = geometry
    before = snapshot(hwnd, target, geometry=geometry, run_dir=run_dir, label="before")
    result["before"] = before
    session = find_session(before.get("sessions") or [], target)
    result["session"] = session
    if not isinstance(session, dict):
        result["error"] = "target_session_not_found"
        write_json(run_dir / "result.json", result)
        return result
    default_x = sidecar.session_click_x_for_geometry(geometry)
    click_x, click_y, click_meta = sidecar.choose_session_row_click_point(session, geometry, default_x=default_x)
    result["planned_click"] = {"x": click_x, "y": click_y, "meta": click_meta, "default_x": default_x}
    time.sleep(0.8)
    if mode == "client":
        sidecar.human_client_click(hwnd, click_x, click_y)
    elif mode == "window":
        bounds = [
            max(74, int(click_x) - 80),
            max(88, int(click_y) - 24),
            min(int(geometry.get("width") or 0) - 48, int(click_x) + 96),
            min(int(geometry.get("height") or 0) - 18, int(click_y) + 28),
        ]
        result["window_click"] = sidecar.human_window_image_click_in_bounds(
            hwnd,
            click_x,
            click_y,
            bounds=bounds,
            action_name="diagnostic_session_row_window_click",
        )
    else:
        result["error"] = "unsupported_mode"
        write_json(run_dir / "result.json", result)
        return result
    time.sleep(1.6)
    after = snapshot(hwnd, target, geometry=geometry, run_dir=run_dir, label=f"after_{mode}")
    result["after"] = after
    result["ok"] = bool(after.get("active_match"))
    if not result["ok"]:
        result["error"] = "target_not_active_after_single_click"
    result["finished_at"] = now_text()
    write_json(run_dir / "result.json", result)
    return result


def main() -> int:
    sidecar.configure_dpi_awareness()
    parser = argparse.ArgumentParser(description="Diagnostic single-click session activation probe. Does not type or send.")
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--target", default="许聪")
    parser.add_argument("--mode", choices=["client", "window"], default="client")
    args = parser.parse_args()
    result = run_probe(str(args.run_id), str(args.target or ""), str(args.mode))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
