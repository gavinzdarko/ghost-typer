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
