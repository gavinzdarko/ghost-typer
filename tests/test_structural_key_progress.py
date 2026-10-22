import threading
from unittest.mock import Mock

from orchestrator_support import Orchestrator
from src.models import PressKey, Rewrite, Settings, TypeText, TypingPlan, TypingProfile
from src.typing_engine import TypingEngine


def test_structural_text_events_complete_progress_after_the_final_newline():
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    target._profile = TypingProfile.defaults()
    target._profile.orchestration.progress_report_frequency = 1
    plan = TypingPlan(actions=[TypeText(text="a"), PressKey(key="enter"),
        Rewrite(delete_count=0, new_actions=[PressKey(key="tab"), PressKey(key="space")]),
        PressKey(key="return"), PressKey(key="left")])
    target._total_chars = target._count_typed_chars(plan.actions)
    target._chars_typed = 0
    target._typing_start_time = 1.0
    progress = []
    target.on_progress = lambda count, total, *_: progress.append((count, total))
    target._execute_plan(plan, TypingEngine(Settings()), Mock(is_active=True))
    assert target._total_chars == 5
    assert target._chars_typed == 5
    assert progress == [(i, 5) for i in range(1, 6)]


def test_cancelled_structural_delay_does_not_advance_progress():
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    target._profile = TypingProfile.defaults()
    target._chars_typed = 0
    simulator = Mock(is_active=True)
    simulator.wait.side_effect = lambda _: target._cancel_event.set()
    target._execute_press_key(PressKey(key="enter"), TypingEngine(Settings()), simulator, "")
    assert target._chars_typed == 0
    simulator.press_key.assert_not_called()
