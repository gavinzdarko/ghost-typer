import threading
from unittest.mock import Mock

import pytest

from orchestrator_support import Orchestrator
from src.models import DistractionPause, Pause, Rewrite, Settings, TypingPlan, TypingProfile
from src.typing_engine import TypingEngine


@pytest.mark.parametrize('nested', [False, True])
def test_ordinary_pauses_recover_fatigue_and_reset_burst_context(nested):
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    target._profile = TypingProfile.defaults()
    engine = TypingEngine(Settings())
    engine.state.fatigue_level = .5
    engine.state.words_since_pause = 12
    simulator = Mock(is_active=True)
    pause = Pause(duration=2)
    action = Rewrite(delete_count=0, new_actions=[pause]) if nested else pause
    target._execute_plan(TypingPlan(actions=[action]), engine, simulator)
    assert engine.state.fatigue_level == pytest.approx(.5 - 2 * engine.profile.fatigue.pause_recovery_rate)
    assert engine.state.words_since_pause == 0


def test_cancelled_pause_does_not_claim_unfinished_rest():
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    engine = TypingEngine(Settings())
    engine.state.fatigue_level = .5
    engine.state.words_since_pause = 12
    simulator = Mock(is_active=True)
    simulator.wait.side_effect = lambda duration: target._cancel_event.set()
    target._execute_plan(TypingPlan(actions=[Pause(duration=60)]), engine, simulator)
    assert engine.state.fatigue_level == .5
    assert engine.state.words_since_pause == 12


def test_distraction_pauses_reset_the_same_runtime_context():
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    engine = TypingEngine(Settings())
    engine.state.words_since_pause = 12
    target._execute_action(DistractionPause(duration=2), engine, Mock(is_active=True), '')
    assert engine.state.words_since_pause == 0
