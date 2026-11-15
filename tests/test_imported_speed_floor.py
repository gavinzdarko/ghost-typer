"""Imported calibration speed agrees with playback's supported minimum."""
import pytest

from src.models import Settings
from src.typing_engine import TypingEngine


@pytest.mark.parametrize('requested', [1, 5, 9, 10, 60, 300, 1000])
def test_imported_speed_matches_zero_variance_playback(requested):
    settings = Settings.from_dict({'wpm': requested, 'wpm_variance': 0})
    engine = TypingEngine(settings)
    expected = max(10, requested)
    assert settings.wpm == expected
    assert engine.state._effective_wpm == settings.wpm
    assert engine.base_delay_for_char('a') == pytest.approx(12 / expected)
    assert Settings.from_dict(settings.to_dict()).wpm == expected


@pytest.mark.parametrize('invalid', [0, -1, 1001, True, float('nan')])
def test_invalid_speed_still_uses_default(invalid):
    assert Settings.from_dict({'wpm': invalid}).wpm == Settings().wpm
