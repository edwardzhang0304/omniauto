"""Contract checks for Win32/OCR capture planning helpers."""

from __future__ import annotations

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters import wechat_win32_ocr_sidecar as sidecar  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr import capture  # noqa: E402


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class FakeWin32Gui:
    @staticmethod
    def GetWindowRect(_hwnd: int) -> tuple[int, int, int, int]:
        return (100, 50, 1081, 910)


def test_capture_module_exports_expected_helpers() -> None:
    for name in (
        "capture_rect_candidates",
        "collect_capture_candidates",
        "capture_window_by_rect",
        "try_image_grab",
        "select_best_capture_candidate",
    ):
        assert_true(callable(getattr(capture, name, None)), f"capture helper missing: {name}")


def test_capture_rect_candidates_preserve_base_only_when_scale_is_normal() -> None:
    rects = capture.capture_rect_candidates((100, 50, 1081, 910), dpi_scale=1.0)
    assert_true(rects == [(100, 50, 1081, 910)], f"normal scale rect candidates mismatch: {rects}")


def test_capture_rect_candidates_preserve_scaled_order() -> None:
    rects = capture.capture_rect_candidates((100, 50, 1081, 910), dpi_scale=1.25)
    expected = [
        (100, 50, 1081, 910),
        (80, 40, 865, 728),
        (125, 62, 1351, 1138),
    ]
    assert_true(rects == expected, f"scaled rect candidates mismatch: {rects}")


def test_collect_capture_candidates_matches_sidecar_order_with_fake_grabber() -> None:
    original_win32gui = sidecar.win32gui
    original_dpi = sidecar.window_dpi_scale
    original_grab = sidecar.try_image_grab
    calls: list[tuple[int, int, int, int]] = []

    def fake_grab(rect: tuple[int, int, int, int]) -> str | None:
        calls.append(rect)
        return None if rect == (80, 40, 865, 728) else f"image:{rect}"

    try:
        sidecar.win32gui = FakeWin32Gui()
        sidecar.window_dpi_scale = lambda _hwnd: 1.25
        sidecar.try_image_grab = fake_grab
        sidecar_result = sidecar.capture_window_by_rect(1001)
    finally:
        sidecar.win32gui = original_win32gui
        sidecar.window_dpi_scale = original_dpi
        sidecar.try_image_grab = original_grab

    expected_calls = [
        (100, 50, 1081, 910),
        (80, 40, 865, 728),
        (125, 62, 1351, 1138),
    ]
    assert_true(calls == expected_calls, f"sidecar grab order mismatch: {calls}")
    extracted_result = capture.collect_capture_candidates(
        (100, 50, 1081, 910),
        dpi_scale=1.25,
        grabber=lambda rect: None if rect == (80, 40, 865, 728) else f"image:{rect}",
    )
    assert_true(
        sidecar_result == extracted_result == ["image:(100, 50, 1081, 910)", "image:(125, 62, 1351, 1138)"],
        f"capture candidates mismatch: sidecar={sidecar_result}, extracted={extracted_result}",
    )


def test_capture_window_by_rect_wrapper_matches_sidecar_with_fake_dependencies() -> None:
    original_win32gui = sidecar.win32gui
    original_dpi = sidecar.window_dpi_scale
    original_grab = sidecar.try_image_grab
    try:
        sidecar.win32gui = FakeWin32Gui()
        sidecar.window_dpi_scale = lambda _hwnd: 1.25
        sidecar.try_image_grab = lambda rect: None if rect == (80, 40, 865, 728) else f"image:{rect}"
        sidecar_result = sidecar.capture_window_by_rect(1001)
    finally:
        sidecar.win32gui = original_win32gui
        sidecar.window_dpi_scale = original_dpi
        sidecar.try_image_grab = original_grab
    extracted_result = capture.capture_window_by_rect(
        1001,
        rect_provider=lambda _hwnd: (100, 50, 1081, 910),
        dpi_scale_provider=lambda _hwnd: 1.25,
        grabber=lambda rect: None if rect == (80, 40, 865, 728) else f"image:{rect}",
    )
    assert_true(extracted_result == sidecar_result, f"capture_window_by_rect mismatch: {extracted_result} != {sidecar_result}")


def test_try_image_grab_matches_sidecar_for_small_rect_success_and_failure() -> None:
    original_grab = sidecar.ImageGrab.grab
    calls: list[tuple[int, int, int, int]] = []

    def fake_grab(*, bbox):
        calls.append(bbox)
        if bbox == (10, 10, 50, 50):
            return "image-ok"
        raise RuntimeError("grab boom")

    try:
        sidecar.ImageGrab.grab = fake_grab
        assert_true(sidecar.try_image_grab((0, 0, 2, 50)) is None, "small width should not grab")
        assert_true(sidecar.try_image_grab((0, 0, 50, 2)) is None, "small height should not grab")
        assert_true(sidecar.try_image_grab((10, 10, 50, 50)) == "image-ok", "successful grab mismatch")
        assert_true(sidecar.try_image_grab((20, 20, 60, 60)) is None, "grab exception should return None")
    finally:
        sidecar.ImageGrab.grab = original_grab

    assert_true(calls == [(10, 10, 50, 50), (20, 20, 60, 60)], f"unexpected grab calls: {calls}")
    assert_true(
        capture.try_image_grab((0, 0, 2, 50), image_grabber=fake_grab) is None,
        "extracted small width should not grab",
    )
    assert_true(
        capture.try_image_grab((10, 10, 50, 50), image_grabber=fake_grab) == "image-ok",
        "extracted successful grab mismatch",
    )


def test_select_best_capture_candidate_matches_sidecar_max_score_semantics() -> None:
    candidates = ["low", "high", "mid"]
    scores = {"low": 0.2, "high": 9.5, "mid": 3.0}
    selected = capture.select_best_capture_candidate(candidates, score=lambda image: scores[image])
    assert_true(selected == "high", f"best candidate mismatch: {selected}")
    assert_true(capture.select_best_capture_candidate([], score=lambda _image: 1.0) is None, "empty candidates should return None")


def main() -> int:
    tests = [
        test_capture_module_exports_expected_helpers,
        test_capture_rect_candidates_preserve_base_only_when_scale_is_normal,
        test_capture_rect_candidates_preserve_scaled_order,
        test_collect_capture_candidates_matches_sidecar_order_with_fake_grabber,
        test_capture_window_by_rect_wrapper_matches_sidecar_with_fake_dependencies,
        test_try_image_grab_matches_sidecar_for_small_rect_success_and_failure,
        test_select_best_capture_candidate_matches_sidecar_max_score_semantics,
    ]
    passed = 0
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
        passed += 1
    print(f"All {passed} WeChat Win32/OCR capture checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
