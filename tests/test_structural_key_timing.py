import threading
from unittest.mock import Mock

import pytest

from orchestrator_support import Orchestrator
from src.models import PressKey, Settings, TypingPlan, TypingProfile
from src.typing_engine import TypingEngine


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('key', ['enter', 'tab', 'space', 'return'])
def test_structural_keys_reset_runtime_word_and_count_as_typed_events(key, nested):
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    target._profile = TypingProfile.defaults()
    engine = TypingEngine(Settings())
    for char in 'word':
        engine.on_char_typed(char)
    simulator = Mock(is_active=True)
    events = []
    simulator.wait.side_effect = lambda _: events.append('wait')
    simulator.press_key.side_effect = lambda _: events.append('key')
    action = PressKey(key=key)
    if nested:
        target._execute_action(action, engine, simulator, 'd')
    else:
        target._execute_plan(TypingPlan(actions=[action]), engine, simulator)
    assert engine.state.current_word == ''
    assert engine.state.chars_typed == 5
    assert engine.state.words_since_pause == 1
    assert events == ['wait', 'key']


def test_cancelled_structural_delay_emits_no_key_and_does_not_claim_a_boundary():
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    target._profile = TypingProfile.defaults()
    engine = TypingEngine(Settings())
    engine.on_char_typed('a')
    simulator = Mock(is_active=True)
    simulator.wait.side_effect = lambda _: target._cancel_event.set()
    target._execute_action(PressKey(key='enter'), engine, simulator, 'a')
    simulator.press_key.assert_not_called()
    assert engine.state.current_word == 'a'


def test_navigation_forgets_word_context_without_counting_as_typed_text():
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    target._profile = TypingProfile.defaults()
    engine = TypingEngine(Settings())
    engine.on_char_typed('a')
    target._execute_action(PressKey(key='left'), engine, Mock(is_active=True), 'a')
    assert engine.state.current_word == ''
    assert engine.state.chars_typed == 1
