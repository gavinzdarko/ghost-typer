from pathlib import Path
from unittest.mock import patch
import subprocess

from src import visual_verifier as module


def test_all_display_outputs_are_removed_after_verification():
    verifier = module.VisualVerifier()
    outputs = []
    def capture(command, **kwargs):
        path = Path(command[-1])
        outputs.extend([path, path.with_name('screen2.png')])
        for output in outputs:
            output.write_bytes(b'private display contents')
    with patch.object(module, 'HAS_TESSERACT', True), patch.object(module.subprocess, 'run', side_effect=capture), patch.object(verifier, 'extract_text', return_value='expected'):
        assert verifier.verify('expected', delay_before_capture=0).success
    assert all(not path.exists() for path in outputs)
    assert not outputs[0].parent.exists()
    assert verifier._capture_directories == {}


def test_capture_failure_cleans_companion_outputs_and_directory():
    verifier = module.VisualVerifier()
    outputs = []
    def capture(command, **kwargs):
        path = Path(command[-1])
        outputs.extend([path, path.with_name('screen2.png')])
        for output in outputs:
            output.write_bytes(b'private display contents')
        raise subprocess.TimeoutExpired(command, 5)
    with patch.object(module.subprocess, 'run', side_effect=capture):
        assert verifier.capture_screen() is None
    assert all(not path.exists() for path in outputs)
    assert not outputs[0].parent.exists()
