import threading
from unittest.mock import Mock, patch

from src import visual_verifier as module


def test_cancelled_capture_delay_returns_without_a_desktop_screenshot():
    event = threading.Event()
    verifier = module.VisualVerifier()
    verifier.capture_screen = Mock()
    worker = threading.Thread(target=lambda: verifier.verify("text", delay_before_capture=60, cancel_event=event))
    with patch.object(module, "HAS_TESSERACT", True):
        worker.start()
        event.set()
        worker.join(1)
    assert not worker.is_alive()
    verifier.capture_screen.assert_not_called()


def test_cancel_during_capture_skips_ocr_and_still_removes_screenshot(tmp_path):
    event = threading.Event()
    screenshot = tmp_path / "private.png"
    screenshot.write_bytes(b"private screen")
    verifier = module.VisualVerifier()
    def capture(_):
        event.set()
        return screenshot
    verifier.capture_screen = Mock(side_effect=capture)
    verifier.extract_text = Mock()
    with patch.object(module, "HAS_TESSERACT", True):
        result = verifier.verify("text", delay_before_capture=0, cancel_event=event)
    assert result.message == "Verification cancelled"
    verifier.extract_text.assert_not_called()
    assert not screenshot.exists()


def test_cancel_during_ocr_skips_comparison_and_cleans_up(tmp_path):
    event = threading.Event()
    screenshot = tmp_path / "private.png"
    screenshot.touch()
    verifier = module.VisualVerifier()
    verifier.capture_screen = Mock(return_value=screenshot)
    def ocr(_):
        event.set()
        return "text"
    verifier.extract_text = Mock(side_effect=ocr)
    verifier._compare_texts = Mock()
    with patch.object(module, "HAS_TESSERACT", True):
        verifier.verify("text", delay_before_capture=0, cancel_event=event)
    verifier._compare_texts.assert_not_called()
    assert not screenshot.exists()
