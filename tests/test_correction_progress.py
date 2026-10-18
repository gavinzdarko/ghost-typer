import threading
from unittest.mock import Mock

import pytest

from orchestrator_support import Orchestrator
from src.models import AbandonWord, MakeMistake, Settings, TypeText, TypingProfile
from src.typing_engine import TypingEngine


def app(total):
    target = Orchestrator.__new__(Orchestrator)
    target._cancel_event = threading.Event()
    target._profile = TypingProfile.defaults()
    target._profile.orchestration.progress_report_frequency = 2
    target._chars_typed = 0
    target._total_chars = total
    target._typing_start_time = 10
    target.on_progress = Mock()
    return target


@pytest.mark.parametrize('action', [MakeMistake(wrong_text='wrnog', correct_text='right'),
                                   AbandonWord(partial_text='rough', replacement_text='right')])
def test_correction_only_actions_report_progress_and_completion(action):
    target = app(10)
    simulator = Mock(is_active=True)
    target._execute_action(action, TypingEngine(Settings()), simulator, '')
    assert simulator.type_char.call_count == 10
    assert [call.args[0] for call in target.on_progress.call_args_list] == [2, 4, 6, 8, 10]
    assert target.on_progress.call_args.args == (10, 10, 10)


def test_short_final_tail_reports_its_last_character():
    target = app(3)
    target._execute_type_text(TypeText(text='abc'), TypingEngine(Settings()), Mock(is_active=True), '')
    assert [call.args[0] for call in target.on_progress.call_args_list] == [2, 3]


def test_callback_snapshot_remains_safe_when_it_unsubscribes_itself():
    target = app(3)
    calls = []
    def progress(*args):
        calls.append(args)
        target.on_progress = None
    target.on_progress = progress
    target._execute_type_text(TypeText(text='abc'), TypingEngine(Settings()), Mock(is_active=True), '')
    assert len(calls) == 1
