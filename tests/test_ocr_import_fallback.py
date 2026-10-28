"""Optional native preprocessing failures must preserve basic OCR."""

import builtins
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from src import visual_verifier as module


@pytest.mark.parametrize("dependency", ["cv2", "numpy"])
@pytest.mark.parametrize("error_type", [ImportError, OSError, ValueError])
def test_native_import_failure_falls_back_without_retry(monkeypatch, tmp_path, dependency, error_type):
    image = MagicMock()
    source = image.open.return_value.__enter__.return_value
    tesseract = Mock()
    tesseract.image_to_string.return_value = " Expected text \n"
    monkeypatch.setattr(module, "HAS_TESSERACT", True)
    monkeypatch.setattr(module, "HAS_OPENCV", True)
    monkeypatch.setattr(module, "Image", image)
    monkeypatch.setattr(module, "pytesseract", tesseract)
    monkeypatch.setattr(module, "cv2", None)
    monkeypatch.setattr(module, "np", None)
    original_import = builtins.__import__
    imports = []

    def load(name, *args, **kwargs):
        if name in {"cv2", "numpy"}:
            imports.append(name)
            if name == dependency:
                raise error_type("Native extension could not load")
            return SimpleNamespace()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", load)
    verifier = module.VisualVerifier()
    for _ in range(2):
        assert verifier.extract_text(tmp_path / "screenshot.png") == "Expected text"

    assert imports.count(dependency) == 1
    assert not module.HAS_OPENCV
    assert module.cv2 is None and module.np is None
    assert tesseract.image_to_string.call_count == 2
    tesseract.image_to_string.assert_called_with(source, timeout=10)
    assert image.open.return_value.__exit__.call_count == 2
    source.convert.assert_not_called()
