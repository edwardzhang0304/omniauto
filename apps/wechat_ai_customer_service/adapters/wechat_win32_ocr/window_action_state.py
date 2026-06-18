"""Pure window action state helpers for the Windows WeChat Win32/OCR adapter."""

from __future__ import annotations

from typing import Any


FOREGROUND_READY_REASONS = frozenset({"foreground_matches_target", "foreground_root_matches_target"})


def foreground_guard_ready(guard: dict[str, Any] | None) -> bool:
    if not isinstance(guard, dict):
        return False
    return bool(guard.get("ok")) and str(guard.get("reason") or "") in FOREGROUND_READY_REASONS


def tray_hidden_from_counts(*, main_count: Any, visible_main_count: Any) -> bool:
    try:
        parsed_main_count = int(main_count or 0)
        parsed_visible_main_count = int(visible_main_count or 0)
    except Exception:
        return False
    return bool(parsed_main_count > 0 and parsed_visible_main_count <= 0)


def tray_hidden_from_probe(probe: dict[str, Any]) -> bool:
    return tray_hidden_from_counts(
        main_count=(probe or {}).get("main_count"),
        visible_main_count=(probe or {}).get("visible_main_count"),
    )
