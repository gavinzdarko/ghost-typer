import pytest

from src.models import TypeText
from src.typing_planner import TypingPlanner


@pytest.mark.parametrize("word", ["photosynthesis", "Photosynthesis,", "photosynthesis.",
    "(photosynthesis)", "“photosynthesis!”", "[PHOTOSYNTHESIS];"])
def test_punctuation_wrappers_do_not_disable_word_speed(word):
    p = TypingPlanner(ai_enabled=False)
    p.profile.behaviors.pre_word_pause.enabled = False
    p._behavioral_content = {"word_speed_map": [{"word": "photosynthesis", "multiplier": 2}]}
    actions = p._build_word_speed_actions(word)
    typed = [a for a in actions if isinstance(a, TypeText)]
    assert "".join(a.text for a in typed) == word
    assert all(a.speed_multiplier == .5 for a in typed)


def test_cached_map_keys_normalize_punctuation_without_losing_technical_symbols():
    p = TypingPlanner(ai_enabled=False)
    p._behavioral_content = {"word_speed_map": [
        {"word": "example,", "multiplier": 2}, {"word": "C++", "multiplier": 3},
        {"word": "C#", "multiplier": 4}, {"word": "C", "multiplier": 1}]}
    assert p._get_word_speed("Example.") == 2
    assert p._get_word_speed("(C++).") == 3
    assert p._get_word_speed("C#,") == 4
    assert p._get_word_speed("C") == 1
