from unittest.mock import Mock, patch

import pytest

from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.models import (AbandonWord, ApplyFormatting, MakeMistake, PressKey,
                        Rewrite, TypeText, TypingPlan)
from src.planned_text import PlannedText


@pytest.mark.parametrize('actions,expected', [
    ([TypeText(text='A '), AbandonWord(partial_text='dif', replacement_text='hard'),
      TypeText(text=' decision.')], 'A hard decision.'),
    ([TypeText(text='their decision')], 'their decision'),
    ([TypeText(text='A draft'), Rewrite.simple(5, 'choice')], 'A choice'),
    ([MakeMistake(wrong_text='teh', correct_text='the'), PressKey(key='space'),
      TypeText(text='end'), PressKey(key='return')], 'the end\n'),
    ([ApplyFormatting(shortcut=('cmd', 'b')), TypeText(text='bold'),
      ApplyFormatting(shortcut=('cmd', 'b'))], 'bold'),
    ([TypeText(text='word tail'), *[PressKey(key='left') for _ in range(4)],
      *[ApplyFormatting(shortcut=('shift', 'right')) for _ in range(4)],
      TypeText(text='ending')], 'word ending'),
])
def test_verification_uses_final_planned_text(actions, expected):
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False, 'start_delay': 0}):
        app = Orchestrator()
    app.notification_service = Mock()
    app.fallback_planner.plan = Mock(return_value=TypingPlan(actions=actions))
    app._execute_plan = Mock()
    app.visual_verifier = Mock(enabled=True)
    with patch('src.orchestrator.KeystrokeSimulator', return_value=Mock(is_active=True)):
        app._typing_pipeline(ClipboardContent('Original source.'))
    app.visual_verifier.verify.assert_called_once_with(expected, cancel_event=app._cancel_event)


def test_unknown_navigation_does_not_verify_a_guessed_document():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False, 'start_delay': 0}):
        app = Orchestrator()
    app.notification_service = Mock()
    app.fallback_planner.plan = Mock(return_value=TypingPlan(actions=[PressKey(key='home'), TypeText(text='new')]))
    app._execute_plan = Mock()
    app.visual_verifier = Mock(enabled=True)
    with patch('src.orchestrator.KeystrokeSimulator', return_value=Mock(is_active=True)):
        app._typing_pipeline(ClipboardContent('Original source.'))
    app.visual_verifier.verify.assert_not_called()
    app.notification_service.notify_error.assert_called_once_with('Visual verification unavailable for this typing session')


def test_verification_formatting_support_keeps_edit_planning_conservative():
    state = PlannedText().apply([ApplyFormatting(shortcut=('cmd', 'b')), TypeText(text='word')])
    assert not state.valid
