from unittest.mock import Mock, patch

from src.clipboard_monitor import ClipboardContent
from src.models import TextSegment, TypingPlan, TypeText
from test_table_retention import app


def test_table_progress_is_cumulative_across_differently_sized_cells():
    target = app()
    target.fallback_planner.plan.side_effect = lambda segments, **kwargs: TypingPlan(actions=[TypeText(text=segments[0].text)])
    target._profile.orchestration.progress_report_frequency = 1
    target.on_progress = Mock()
    def execute(plan, engine, simulator):
        for action in plan.actions:
            for char in action.text:
                engine.on_char_typed(char)
                target._record_typed_character()
    target._execute_plan.side_effect = execute
    with patch('src.orchestrator.KeystrokeSimulator', return_value=Mock(is_active=True)):
        target._table_fill_pipeline([ClipboardContent('one'), ClipboardContent('three')])
    progress = [call.args for call in target.on_progress.call_args_list]
    assert [(call[0], call[1]) for call in progress] == [(i, 8) for i in range(9)]
    assert len({call[2] for call in progress}) == 1
    assert progress[0][3] > 0
    assert target.fallback_planner.plan.call_count == 2
    target.notification_service.notify_start.assert_called_once_with(2)
    target.notification_service.notify_complete.assert_called_once()


def test_invalid_later_cell_is_rejected_before_typing_an_earlier_cell():
    target = app()
    target.text_parser.parse.side_effect = [[TextSegment('first')], []]
    with patch('src.orchestrator.KeystrokeSimulator') as simulator:
        target._table_fill_pipeline([ClipboardContent('first'), ClipboardContent('invalid')])
    simulator.assert_not_called()
    target._execute_plan.assert_not_called()
    assert [item.text for item in target._table_queue] == ['first', 'invalid']
