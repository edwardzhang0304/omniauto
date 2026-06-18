"""Capture planning helpers for the Windows WeChat Win32/OCR adapter."""

from __future__ import annotations

from typing import Any, Callable


Rect = tuple[int, int, int, int]


def normalize_rect(rect: Any) -> Rect:
    left, top, right, bottom = rect
    return (int(left), int(top), int(right), int(bottom))


def capture_rect_candidates(rect: Any, *, dpi_scale: float = 1.0) -> list[Rect]:
    base = normalize_rect(rect)
    candidates = [base]
    scale = float(dpi_scale or 1.0)
    if scale > 1.05:
        candidates.append(
            (
                int(round(float(base[0]) / scale)),
                int(round(float(base[1]) / scale)),
                int(round(float(base[2]) / scale)),
                int(round(float(base[3]) / scale)),
            )
        )
        candidates.append(
            (
                int(round(float(base[0]) * scale)),
                int(round(float(base[1]) * scale)),
                int(round(float(base[2]) * scale)),
                int(round(float(base[3]) * scale)),
            )
        )
    return candidates


def collect_capture_candidates(
    rect: Any,
    *,
    dpi_scale: float,
    grabber: Callable[[Rect], Any | None],
) -> list[Any]:
    captures: list[Any] = []
    for candidate_rect in capture_rect_candidates(rect, dpi_scale=dpi_scale):
        image = grabber(candidate_rect)
        if image is not None:
            captures.append(image)
    return captures


def select_best_capture_candidate(
    candidates: list[Any],
    *,
    score: Callable[[Any], float],
) -> Any | None:
    if not candidates:
        return None
    return max(candidates, key=score)
