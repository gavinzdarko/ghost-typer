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
from importlib.util import find_spec
import subprocess
import tempfile
import time
from threading import Event
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Discover extras without importing their native libraries or data-science
# dependencies during every app startup. Most sessions never enable OCR.
HAS_OPENCV = find_spec("cv2") is not None and find_spec("numpy") is not None
HAS_TESSERACT = find_spec("pytesseract") is not None and find_spec("PIL") is not None
cv2 = np = pytesseract = Image = None


class VisualVerifier:
    """Verifies typed output by screenshotting and OCR-ing the result."""

    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)
        self._capture_directories = {}
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
        capture_directory = None
        try:
            # macOS can write one image per display, including companion files
            # not named in the command. Own the entire output directory.
            capture_directory = tempfile.TemporaryDirectory(prefix="ghost-typer-capture-")
            path = str(Path(capture_directory.name) / "screen.png")

            if region:
                x, y, w, h = region
                cmd = ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path]
            else:
                cmd = ["screencapture", "-x", path]

            subprocess.run(cmd, check=True, capture_output=True, timeout=5)
            screenshot = Path(path)
            self._capture_directories[screenshot] = capture_directory
            logger.info("Screenshot saved to %s", path)
            return screenshot
        except Exception:
            logger.exception("Failed to capture screenshot")
            if capture_directory is not None:
                capture_directory.cleanup()
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
            global cv2, np, pytesseract, Image
            if Image is None:
                from PIL import Image
            if pytesseract is None:
                import pytesseract
            if HAS_OPENCV and cv2 is None:
                import cv2
                import numpy as np
            with Image.open(image_path) as source:
                if HAS_OPENCV:
                    img_array = np.array(source.convert("RGB"))
                    gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
                    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                    with Image.fromarray(thresh) as processed:
                        text = pytesseract.image_to_string(processed, timeout=10)
                else:
                    text = pytesseract.image_to_string(source, timeout=10)
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
        cancel_event: Optional[Event] = None,
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

        if cancel_event is not None and cancel_event.is_set():
            return VerificationResult(False, 0.0, "Verification cancelled")

        if not HAS_TESSERACT:
            return VerificationResult(
                success=False, match_ratio=0.0,
                message="OCR verification unavailable: install Tesseract and the verification extras",
            )

        if cancel_event is None:
            time.sleep(delay_before_capture)
        elif cancel_event.wait(max(0.0, delay_before_capture)):
            return VerificationResult(False, 0.0, "Verification cancelled")

        # Capture screenshot
        screenshot = self.capture_screen(region)
        if not screenshot:
            return VerificationResult(
                success=False,
                match_ratio=0.0,
                message="Failed to capture screenshot",
            )

        try:
            if cancel_event is not None and cancel_event.is_set():
                return VerificationResult(False, 0.0, "Verification cancelled")
            extracted = self.extract_text(screenshot)
            if cancel_event is not None and cancel_event.is_set():
                return VerificationResult(False, 0.0, "Verification cancelled")
            if extracted is None:
                return VerificationResult(
                    success=False, match_ratio=0.0, message="OCR extraction failed",
                )
            try:
                match_ratio = self._compare_texts(intended_text, extracted)
            except ValueError as exc:
                return VerificationResult(success=False, match_ratio=0.0, message=str(exc))
        finally:
            capture_directory = self._capture_directories.pop(screenshot, None)
            if capture_directory is not None:
                capture_directory.cleanup()
            else:
                try:
                    screenshot.unlink()
                except OSError:
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
        """Compare normalized text with bounded, ordered character matching."""
        intended_clean = " ".join(intended.lower().split())
        extracted_clean = " ".join(extracted.lower().split())
        if intended_clean == extracted_clean:
            return 1.0
        if not intended_clean or not extracted_clean:
            return 0.0
        # Trim shared edges first: nearly identical long passages and leading
        # OCR noise need only linear work, even when their words repeat.
        prefix = 0
        limit = min(len(intended_clean), len(extracted_clean))
        while prefix < limit and intended_clean[prefix] == extracted_clean[prefix]:
            prefix += 1
        suffix = 0
        while (suffix < limit - prefix
               and intended_clean[-suffix - 1] == extracted_clean[-suffix - 1]):
            suffix += 1
        before = intended_clean[prefix:len(intended_clean) - suffix]
        after = extracted_clean[prefix:len(extracted_clean) - suffix]
        if len(before) * len(after) > 4_000_000:
            raise ValueError("OCR comparison exceeds the safe text limit; verify a smaller region")
        from difflib import SequenceMatcher
        # Keep small within-word/punctuation OCR errors proportional to their
        # character count; word equality made a missing comma fail a short line.
        matched = prefix + suffix + sum(block.size for block in
            SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks())
        return 2.0 * matched / (len(intended_clean) + len(extracted_clean))


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
