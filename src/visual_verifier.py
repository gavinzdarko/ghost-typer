"""
Visual verification service using OCR (Tesseract) and screenshot comparison.

After Ghost Typer finishes typing, this module can:
1. Take a screenshot of the target area
2. OCR the screenshot to extract what was actually typed
3. Compare it against what was intended
4. Report any discrepancies
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import optional dependencies
try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False
    logger.info("OpenCV not available — visual verification will use basic mode")

try:
    import pytesseract
    from PIL import Image
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False
    logger.info("Tesseract/Pillow not available — OCR verification disabled")


class VisualVerifier:
    """Verifies typed output by screenshotting and OCR-ing the result."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled and (HAS_TESSERACT or HAS_OPENCV)
        if self.enabled:
            logger.info("Visual verifier initialized (OCR: %s, CV: %s)", HAS_TESSERACT, HAS_OPENCV)
        else:
            logger.info("Visual verifier disabled — missing dependencies")

    def capture_screen(self, region: Optional[tuple[int, int, int, int]] = None) -> Optional[Path]:
        """Capture a screenshot of the screen or a region.

        Args:
            region: Optional (x, y, width, height) tuple. If None, captures full screen.

        Returns:
            Path to the saved screenshot, or None on failure.
        """
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.close()
            path = tmp.name

            if region:
                x, y, w, h = region
                cmd = ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path]
            else:
                cmd = ["screencapture", "-x", path]

            subprocess.run(cmd, check=True, capture_output=True, timeout=5)
            logger.info("Screenshot saved to %s", path)
            return Path(path)
        except Exception:
            logger.exception("Failed to capture screenshot")
            return None

    def extract_text(self, image_path: Path) -> Optional[str]:
        """Extract text from an image using Tesseract OCR.

        Args:
            image_path: Path to the screenshot image.

        Returns:
            Extracted text, or None if OCR fails.
        """
        if not HAS_TESSERACT:
            logger.warning("Tesseract not available for OCR")
            return None

        try:
            image = Image.open(image_path)

            # Preprocess if OpenCV is available
            if HAS_OPENCV:
                img_array = np.array(image)
                # Convert to grayscale
                gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
                # Apply threshold to improve OCR accuracy
                _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                image = Image.fromarray(thresh)

            text = pytesseract.image_to_string(image)
            logger.info("OCR extracted %d characters", len(text))
            return text.strip()
        except Exception:
            logger.exception("OCR extraction failed")
            return None

    def verify(
        self,
        intended_text: str,
        region: Optional[tuple[int, int, int, int]] = None,
        delay_before_capture: float = 1.0,
    ) -> VerificationResult:
        """Verify that what was typed matches the intended text.

        Args:
            intended_text: The text that should have been typed.
            region: Screen region to capture (x, y, w, h).
            delay_before_capture: Seconds to wait before capturing.

        Returns:
            A VerificationResult with match info.
        """
        if not self.enabled:
            return VerificationResult(
                success=True,
                match_ratio=1.0,
                message="Verification skipped (disabled)",
            )

        time.sleep(delay_before_capture)

        # Capture screenshot
        screenshot = self.capture_screen(region)
        if not screenshot:
            return VerificationResult(
                success=False,
                match_ratio=0.0,
                message="Failed to capture screenshot",
            )

        # OCR the screenshot
        extracted = self.extract_text(screenshot)
        if extracted is None:
            try:
                screenshot.unlink()
            except Exception:
                pass
            return VerificationResult(
                success=False,
                match_ratio=0.0,
                message="OCR extraction failed",
            )

        # Compare texts
        match_ratio = self._compare_texts(intended_text, extracted)

        # Clean up screenshot
        try:
            screenshot.unlink()
        except Exception:
            pass

        success = match_ratio > 0.85  # 85% match threshold

        return VerificationResult(
            success=success,
            match_ratio=match_ratio,
            intended_text=intended_text,
            extracted_text=extracted,
            message=f"Match: {match_ratio:.1%}" if success else f"Low match: {match_ratio:.1%}",
        )

    @staticmethod
    def _compare_texts(intended: str, extracted: str) -> float:
        """Compare two texts using sequential word matching (0.0 - 1.0)."""
        # Normalize whitespace
        intended_clean = " ".join(intended.split()).lower()
        extracted_clean = " ".join(extracted.split()).lower()

        if not intended_clean:
            return 1.0 if not extracted_clean else 0.0

        # Use SequenceMatcher for order-aware similarity (stdlib, no extra deps)
        from difflib import SequenceMatcher
        return SequenceMatcher(None, intended_clean, extracted_clean).ratio()


class VerificationResult:
    """Result of a visual verification check."""

    def __init__(
        self,
        success: bool,
        match_ratio: float,
        message: str = "",
        intended_text: str = "",
        extracted_text: str = "",
    ):
        self.success = success
        self.match_ratio = match_ratio
        self.message = message
        self.intended_text = intended_text
        self.extracted_text = extracted_text

    def __repr__(self) -> str:
        return f"VerificationResult(success={self.success}, match={self.match_ratio:.1%}, {self.message})"
