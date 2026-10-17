import pytest

from src.models import Settings
from src.typing_engine import TypingEngine
from src.typing_planner import TypingPlanner


@pytest.mark.parametrize("data", [None, [], "invalid", {"wpm": "fast", "error_rate": float("nan"),
    "fatigue_enabled": "false", "burst_length_min": True, "wpm_variance": -1,
    "rewrite_scaling_chars": 0, "burst_speed_multiplier": 0,
    "pause_duration_max": float("inf"), "revisit_max_per_session": 10 ** 1000}])
def test_malformed_saved_settings_fall_back_to_usable_defaults(data):
    settings = Settings.from_dict(data)
    assert settings == Settings()
    engine = TypingEngine(settings)
    assert engine.delay_for_keystroke("a") > 0
    assert TypingPlanner(settings, ai_enabled=False).plan_plain_text("Safe input").actions


def test_invalid_related_limits_and_zero_weights_do_not_reach_random_sampling():
    settings = Settings.from_dict({"correction_delay_chars_min": 20, "correction_delay_chars_max": 3,
        "burst_length_min": 15, "burst_length_max": 5, "pause_duration_min": 8,
        "pause_duration_max": 2, "rewrite_word_weight": 0, "rewrite_sentence_weight": 0,
        "rewrite_paragraph_weight": 0})
    assert settings == Settings()
    assert TypingEngine(settings).pick_rewrite_granularity() in {"word", "sentence", "paragraph"}


def test_valid_settings_round_trip_and_zero_probabilities_are_preserved():
    settings = Settings(wpm=90, fatigue_enabled=False, correction_delay_chars_max=0,
                        rewrite_max_probability=0, rewrite_base_probability=0)
    assert Settings.from_dict({**settings.to_dict(), "future_setting": 10}) == settings
    assert Settings.from_dict({"rewrite_max_probability": 0}).rewrite_base_probability == 0
