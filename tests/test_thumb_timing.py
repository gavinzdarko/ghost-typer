from copy import deepcopy

import pytest

from src.models import Settings, TypingProfile
from src.typing_engine import TypingEngine


def test_personal_thumb_multiplier_changes_space_only():
    normal_profile = TypingProfile.defaults()
    custom_profile = deepcopy(normal_profile)
    custom_profile.keystroke.finger_thumb_multiplier = 1.6
    engines = [TypingEngine(Settings(wpm_variance=0), profile)
               for profile in (normal_profile, custom_profile)]
    for engine in engines:
        engine.seed(10)
    assert engines[1].delay_for_keystroke(' ', 'a') == pytest.approx(
        engines[0].delay_for_keystroke(' ', 'a') * 1.6)
    for engine in engines:
        engine.seed(10)
    assert engines[1].delay_for_keystroke('a') == engines[0].delay_for_keystroke('a')
