from src.models import TypingProfile
from src.typing_planner import TypingPlanner


def test_invalid_ai_profile_fields_keep_safe_defaults():
    p = TypingProfile.from_dict({
        'keystroke': None,
        'pauses': {'thought_pause_sentences_interval': {'min': 5, 'max': 1}},
        'orchestration': {'progress_report_frequency': 0},
        'proofread': {'revisit_length_boost_divisor': 0},
        'mistakes': {'type_weights': {'adjacent': -2}, 'false_alarm_weights': [0, 0]},
        'keys': {'hunt_keys': [{}]},
        'fatigue': {'max_level': float('nan')},
        'behaviors': {'quote': {'speed_multiplier': -1}},
        '__class__': None,
    })
    assert p == TypingProfile.defaults()
    planner = TypingPlanner(profile=p, ai_enabled=False)
    assert planner.plan_plain_text('A safe profile still types.').actions


def test_valid_profile_customization_survives_and_ranges_are_finite():
    p = TypingProfile.from_dict({'keystroke': {'shift_multiplier': {'min': 1.1, 'max': 1.4},
                                             'delay_clamp_min': 3, 'delay_clamp_max': 1},
                                 'peek': {'pause_duration': {'min': 0, 'max': float('inf')}},
                                 'energy_level': .7})
    assert p.keystroke.shift_multiplier.min == 1.1
    assert p.keystroke.delay_clamp_min == TypingProfile.defaults().keystroke.delay_clamp_min
    assert p.peek == TypingProfile.defaults().peek
    assert p.energy_level == .7


def test_extreme_ai_profile_cannot_overflow_or_create_hour_long_keystrokes():
    import math
    from src.models import Settings
    from src.typing_engine import TypingEngine
    p = TypingProfile.from_dict({
        'keystroke': {'bimodal_fast_sigma': 3600, 'bimodal_slow_sigma': 3600,
                      'bimodal_slow_multiplier': 3600, 'delay_clamp_max': 3600,
                      'shift_multiplier': {'min': 0, 'max': 3600},
                      'warmup_slowdown': 10 ** 1000},
        'correction': {'first_backspace_delay': {'min': 0, 'max': 3600}},
    })
    assert p == TypingProfile.defaults()
    engine = TypingEngine(Settings(wpm_variance=0), p)
    engine.seed(0)
    for char in ('The human types carefully! ' * 50):
        delay = engine.delay_for_keystroke(char)
        assert math.isfinite(delay) and .035 <= delay <= 2
        engine.on_char_typed(char)
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
                                    punctuation_error_rate=0), profile=p, ai_enabled=False)
    assert planner.plan_plain_text('The extreme profile falls back safely.').actions


def test_finite_weight_values_cannot_overflow_random_choices_totals():
    from src.typing_engine import TypingEngine

    profile = TypingProfile.from_dict({
        "mistakes": {
            "false_alarm_weights": [1e308, 1e308],
            "type_weights": {"adjacent": 1e308, "double": 1e308},
        },
    })
    assert profile.mistakes == TypingProfile.defaults().mistakes
    engine = TypingEngine(profile=profile)
    assert engine.false_alarm_chars() in (1, 2)
    assert isinstance(engine.generate_typo("t"), str)


def test_bounded_custom_weights_still_select_the_requested_behavior():
    from src.typing_engine import TypingEngine

    profile = TypingProfile.from_dict({
        "mistakes": {
            "false_alarm_weights": [0, 10000],
            "type_weights": {"adjacent": 0, "transpose_skip": 0,
                             "double": 10000, "wrong_shift": 0, "drop": 0},
        },
    })
    engine = TypingEngine(profile=profile)
    assert engine.false_alarm_chars() == 2
    assert engine.generate_typo("t") == "tt"
