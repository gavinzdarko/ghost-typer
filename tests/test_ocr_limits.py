from unittest.mock import MagicMock, Mock, patch

from src import visual_verifier as module


def test_requested_verification_reports_missing_ocr_instead_of_success():
    with patch.object(module, 'HAS_TESSERACT', False):
        verifier = module.VisualVerifier(enabled=True)
        verifier.capture_screen = Mock()
        result = verifier.verify('expected', delay_before_capture=0)
    assert not result.success
    assert 'unavailable' in result.message
    verifier.capture_screen.assert_not_called()


def test_ocr_has_timeout_and_closes_source_on_failure(tmp_path):
    image = MagicMock()
    source = Mock()
    image.open.return_value.__enter__.return_value = source
    tesseract = Mock()
    tesseract.image_to_string.side_effect = RuntimeError('timeout')
    with patch.object(module, 'HAS_TESSERACT', True), patch.object(module, 'HAS_OPENCV', False), patch.object(module, 'Image', image, create=True), patch.object(module, 'pytesseract', tesseract, create=True):
        assert module.VisualVerifier().extract_text(tmp_path / 'test.png') is None
    tesseract.image_to_string.assert_called_once_with(source, timeout=10)
    image.open.return_value.__exit__.assert_called_once()
