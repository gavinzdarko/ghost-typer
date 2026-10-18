from src.models import Pause, TypeText
from src.typing_planner import TypingPlanner


def test_same_speed_merge_constructs_only_linear_text_volume(monkeypatch):
    import src.typing_planner as module

    constructed_chars = 0

    class CountedTypeText(TypeText):
        def __post_init__(self):
            nonlocal constructed_chars
            constructed_chars += len(self.text)
            super().__post_init__()

    monkeypatch.setattr(module, "TypeText", CountedTypeText)
    p = TypingPlanner(ai_enabled=False)
    p._behavioral_content = {"word_speed_map": [{"word": "the", "multiplier": 1}]}
    text = "the " * 5000
    actions = p._build_word_speed_actions(text)
    assert len(actions) == 1
    assert actions[0].text == text
    assert constructed_chars <= 3 * len(text)


def test_merge_preserves_pause_boundaries_and_speed_changes():
    p = TypingPlanner(ai_enabled=False)
    p._behavioral_content = {"word_speed_map": [
        {"word": "easy", "multiplier": .8},
        {"word": "hard", "multiplier": 1.5},
    ], "word_difficulty_ratings": [{"word": "hard", "difficulty": .9}]}
    actions = p._build_word_speed_actions("easy hard easy")
    assert "".join(a.text for a in actions if isinstance(a, TypeText)) == "easy hard easy"
    assert any(isinstance(a, Pause) for a in actions)
    speeds = {a.speed_multiplier for a in actions if isinstance(a, TypeText)}
    assert 1 / .8 in speeds and 1 / 1.5 in speeds
