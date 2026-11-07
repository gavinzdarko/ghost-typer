from threading import Event
from unittest.mock import Mock

import pytest

from orchestrator_support import Orchestrator
from src.models import Range, Rewrite, Settings, TypingPlan, TypingProfile
from src.planned_text import PlannedText
from src.typing_engine import TypingEngine
from src.typing_planner import TypingPlanner


@pytest.mark.parametrize('wrong', ['', 'x', 'aa'])
@pytest.mark.parametrize('nested', [False, True])
def test_motor_corrections_use_reflex_timing_and_update_error_state(wrong, nested):
    planner = TypingPlanner(Settings(error_rate=1, grammar_error_rate=0,
                                    punctuation_error_rate=0), ai_enabled=False)
    planner.engine.generate_typo = lambda _: wrong
    planner.engine.is_fast_loop_correction = lambda: True
    planner.engine.fast_loop_pause = lambda: .12
    planner.profile.mistakes.unnoticed_rate = 0
    actions, consumed, unnoticed = planner._build_mistake('a', 0)
    assert consumed == 1 and unnoticed is None
    if nested:
        actions = [Rewrite(delete_count=0, new_actions=actions)]
    assert PlannedText('z').apply(actions).text == 'za'

    app = Orchestrator.__new__(Orchestrator)
    app._cancel_event = Event()
    app._profile = TypingProfile.defaults()
    app._chars_typed = 0
    app._total_chars = len(wrong) + 1
    app.on_progress = None
    engine = TypingEngine(profile=app._profile)
    engine.on_char_typed('z')
    engine.should_peek_pause = lambda: False
    engine.delay_for_keystroke = lambda *args: .1
    engine.correction_pause_duration = Mock(return_value=1)
    engine.backspace_delay = Mock(return_value=.15)
    engine.profile.correction.fast_loop_backspace_delay = Range(.04, .04)
    engine.fast_loop_backspace_delay = Mock(wraps=engine.fast_loop_backspace_delay)
    simulator = Mock(is_active=True)
    app._execute_plan(TypingPlan(actions=actions), engine, simulator)

    # Only the optional outer semantic rewrite gets its 1 + .3 seconds.
    assert engine.correction_pause_duration.call_count == (2 if nested else 0)
    engine.backspace_delay.assert_not_called()
    assert engine.fast_loop_backspace_delay.call_count == len(wrong)
    waits = [call.args[0] for call in simulator.wait.call_args_list]
    assert sum(waits) == pytest.approx(.12 + .1 * (len(wrong) + 1)
                                      + .04 * len(wrong) + (1.3 if nested else 0))
    assert engine.state.post_error_cooldown > 0
    assert engine.previous_visible_char == 'a'
    assert app._chars_typed == len(wrong) + 1


def test_semantic_rewrites_keep_their_existing_timing():
    app = Orchestrator.__new__(Orchestrator)
    app._cancel_event = Event()
    app._profile = TypingProfile.defaults()
    app._chars_typed = 0
    app._total_chars = 1
    app.on_progress = None
    engine = TypingEngine(profile=app._profile)
    engine.on_char_typed('x')
    engine.should_peek_pause = lambda: False
    engine.delay_for_keystroke = lambda *args: .1
    engine.correction_pause_duration = Mock(return_value=1)
    engine.backspace_delay = Mock(return_value=.15)
    simulator = Mock(is_active=True)
    app._execute_plan(TypingPlan(actions=[Rewrite.simple(1, 'a')]), engine, simulator)
    assert [call.args[0] for call in simulator.wait.call_args_list] == [1, .15, .3, .1]
    assert engine.state.post_error_cooldown == 0
