"""Cell admission examines the whole real-parser result before typing."""
from unittest.mock import Mock, patch

import pytest

from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.planned_text import PlannedText


def app():
    with patch('src.orchestrator.load_settings_dict', return_value={
        'ai_enabled': False, 'start_delay': 0,
        'error_rate': 0, 'grammar_error_rate': 0, 'punctuation_error_rate': 0,
    }):
        target = Orchestrator()
    target.notification_service = Mock()
    target._cell_has_content = Mock(return_value=False)
    target._execute_plan = Mock()
    return target


@pytest.mark.parametrize('content', [
    ClipboardContent(text='\nhello'),
    ClipboardContent(text='hello', html='<br>hello'),
])
def test_leading_structural_segment_does_not_reject_a_typable_cell(content):
    target = app()
    with patch('src.orchestrator.KeystrokeSimulator', return_value=Mock(is_active=True)):
        target._table_fill_pipeline([content])

    target.notification_service.notify_error.assert_not_called()
    target.notification_service.notify_complete.assert_called_once()
    target._execute_plan.assert_called_once()
    plan = target._execute_plan.call_args.args[0]
    replay = PlannedText().apply(plan.actions)
    assert replay.valid
    assert replay.text == '\nhello'
    assert target._table_queue == []


@pytest.mark.parametrize('content', [
    ClipboardContent(text='\n \t'),
    ClipboardContent(text=' ', html='<br><span> </span>'),
])
def test_whitespace_only_cell_is_rejected_without_consuming_it(content):
    target = app()
    with patch('src.orchestrator.KeystrokeSimulator') as simulator:
        target._table_fill_pipeline([content])

    simulator.assert_not_called()
    target._execute_plan.assert_not_called()
    target.notification_service.notify_error.assert_called_once_with(
        'Table item did not contain typable text')
    target.notification_service.notify_complete.assert_not_called()
    assert target._table_queue == [content]
