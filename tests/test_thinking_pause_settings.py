import pytest

from src.models import Settings
from src.typing_engine import TypingEngine


@pytest.mark.parametrize("minimum,maximum", [(.5, .5), (.01, .1), (8, 10), (0, 0)])
def test_thinking_pauses_obey_explicit_user_bounds_even_outside_persona(minimum, maximum):
    engine = TypingEngine(Settings(pause_duration_min=minimum, pause_duration_max=maximum))
    engine.seed(1)
    for _ in range(100):
        assert minimum <= engine.thinking_pause_duration() <= maximum


def test_ai_persona_can_narrow_pauses_within_user_bounds():
    engine = TypingEngine(Settings(pause_duration_min=.3, pause_duration_max=2))
    engine.profile.pauses.thinking_pause_clamp_min = .8
    engine.profile.pauses.thinking_pause_clamp_max = 1.2
    engine.seed(2)
    for _ in range(100):
        assert .8 <= engine.thinking_pause_duration() <= 1.2
