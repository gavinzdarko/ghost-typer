"""Disabled OCR must not load optional native libraries at app startup."""
import subprocess
import sys


def test_verifier_import_does_not_import_ocr_extras():
    script = """
import sys
from src.visual_verifier import VisualVerifier
VisualVerifier(enabled=False)
assert not {'cv2', 'numpy', 'pytesseract', 'PIL'} & sys.modules.keys()
"""
    subprocess.run([sys.executable, "-c", script], check=True)
