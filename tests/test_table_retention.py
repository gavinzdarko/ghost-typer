from unittest.mock import Mock, patch
from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.models import TextSegment, TypingPlan, TypeText


def app():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False, 'start_delay': 0}), patch('src.settings_ui.get_api_key', return_value=''):
        target = Orchestrator()
    target.notification_service = Mock()
    target.text_parser.parse = Mock(side_effect=lambda text, **kw: [TextSegment(text)])
    target.fallback_planner.plan = Mock(return_value=TypingPlan(actions=[TypeText(text='item')]))
    target._cell_has_content = Mock(return_value=False)
    target._execute_plan = Mock()
    return target


def run(target, items):
    simulator = Mock(is_active=True)
    with patch('src.orchestrator.KeystrokeSimulator', return_value=simulator), patch('src.orchestrator.time.sleep'):
        target._table_fill_pipeline([ClipboardContent(item) for item in items])
    return simulator


def test_safety_cutoff_retains_all_untyped_items_without_success_notification():
    target = app()
    target._cell_has_content.return_value = True
    run(target, ['one', 'two'])
    assert [item.text for item in target._table_queue] == ['one', 'two']
    target.notification_service.notify_complete.assert_not_called()
    target.notification_service.notify_error.assert_called_once()


def test_cancel_during_current_item_retains_it_and_following_items():
    target = app()
    def execute(*args):
        if target._execute_plan.call_count == 2:
            target._cancel_event.set()
    target._execute_plan.side_effect = execute
    run(target, ['one', 'two', 'three'])
    assert [item.text for item in target._table_queue] == ['two', 'three']
    target.notification_service.notify_complete.assert_not_called()


def test_error_preserves_pending_items_before_newly_queued_items():
    target = app()
    target._table_queue = [ClipboardContent('new')]
    target._execute_plan.side_effect = RuntimeError('backend failed')
    run(target, ['one', 'two'])
    assert [item.text for item in target._table_queue] == ['one', 'two', 'new']
    target.notification_service.notify_complete.assert_not_called()
    target.notification_service.notify_error.assert_called_once()
