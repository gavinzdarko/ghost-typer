from unittest.mock import Mock, patch

import pytest
from src import visual_verifier as module


def test_repeated_text_with_small_leading_ocr_noise_still_matches():
    intended = "the cat sat on the mat. " * 100
    assert module.VisualVerifier._compare_texts(intended, "noise " + intended) > .99
    assert module.VisualVerifier._compare_texts(intended, "X" + intended) > .99


def test_comparison_keeps_word_order_and_normalizes_case_and_whitespace():
    assert module.VisualVerifier._compare_texts("Hello   world", "hello\nWORLD") == 1
    assert module.VisualVerifier._compare_texts("a b c d", "d c b a") < .85
    assert module.VisualVerifier._compare_texts("", "") == 1
    assert module.VisualVerifier._compare_texts("a", "") == 0


def test_large_nonidentical_comparison_is_bounded_and_cleans_screenshot(tmp_path):
    intended = "a" * 3000
    extracted = "b" * 3000
    with pytest.raises(ValueError, match="safe text limit"):
        module.VisualVerifier._compare_texts(intended, extracted)
    assert module.VisualVerifier._compare_texts(intended, intended) == 1
    assert module.VisualVerifier._compare_texts("word " * 3000, "noise " + "word " * 3000) > .99
    screenshot = tmp_path / "screen.png"
    screenshot.write_bytes(b"private screenshot")
    verifier = module.VisualVerifier()
    verifier.capture_screen = Mock(return_value=screenshot)
    verifier.extract_text = Mock(return_value=extracted)
    with patch.object(module, "HAS_TESSERACT", True):
        result = verifier.verify(intended, delay_before_capture=0)
    assert not result.success
    assert "safe text limit" in result.message
    assert not screenshot.exists()


@pytest.mark.parametrize("intended,extracted", [
    ("The quick brown fox jumps.", "The quick brown fox jumps"),
    ("Hello, world!", "Hello world"),
    ("The quick brown fox jumps.", "The quick br0wn fox jumps."),
])
def test_minor_punctuation_and_within_word_ocr_errors_keep_proportional_similarity(intended, extracted):
    assert module.VisualVerifier._compare_texts(intended, extracted) > .85
