from threading import Event
from unittest.mock import Mock
import pytest
from src.models import TypeText, TypingProfile
from src.orchestrator import Orchestrator
from src.typing_planner import TypingPlanner


def delay(action):
    orch = Orchestrator.__new__(Orchestrator)
    orch._cancel_event = Event()
    orch._profile = TypingProfile.defaults()
    orch._chars_typed = 0
    orch.on_progress = None
    engine = Mock()
    engine.should_peek_pause.return_value = False
    engine.delay_for_keystroke.return_value = 0.2
    sim = Mock(is_active=True)
    orch._execute_type_text(action, engine, sim, '')
    return sim.wait.call_args_list[0].args[0]


def test_quote_and_composition_are_slower_and_copy_is_faster():
    profile = TypingProfile.defaults()
    normal = delay(TypeText(text='x'))
    assert delay(TypeText(text='x', speed_multiplier=profile.behaviors.quote.speed_multiplier)) > normal
    assert delay(TypeText(text='x', speed_multiplier=profile.behaviors.composition_mode.composition_speed_multiplier)) > normal
    assert delay(TypeText(text='x', speed_multiplier=profile.behaviors.composition_mode.copy_typing_speed_multiplier)) < normal


def test_ai_difficulty_map_retains_hard_and_easy_word_order():
    planner = TypingPlanner()
    planner._behavioral_content = {'word_speed_map': [
        {'word': 'photosynthesis', 'multiplier': 1.5},
        {'word': 'the', 'multiplier': 0.7},
    ]}
    actions = planner._build_word_speed_actions('photosynthesis the')
    words = {a.text: a for a in actions if isinstance(a, TypeText) and a.text.strip()}
    assert delay(words['photosynthesis']) > 0.2
    assert delay(words['the']) < 0.2


@pytest.mark.parametrize('value', [0, -1, float('nan'), float('inf')])
def test_invalid_action_speed_is_rejected(value):
    with pytest.raises(ValueError, match='finite and positive'):
        TypeText(text='x', speed_multiplier=value)
