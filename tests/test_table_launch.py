from unittest.mock import Mock, patch
from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.orchestrator import OrchestratorState


def app():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}), patch('src.settings_ui.get_api_key', return_value=''):
        target = Orchestrator()
    target._table_queue = [ClipboardContent('one'), ClipboardContent('two')]
    target._table_fill_mode = True
    target.clipboard_monitor._immediate_mode = True
    return target


def assert_preserved(target):
    assert [item.text for item in target._table_queue] == ['one', 'two']
    assert target.table_fill_mode
    assert target.clipboard_monitor._immediate_mode


def test_busy_table_run_preserves_queue_and_mode():
    target = app()
    target.state = OrchestratorState.TYPING
    target.run_table_fill()
    assert_preserved(target)
    target.state = OrchestratorState.IDLE
    target._typing_thread = Mock()
    target._typing_thread.is_alive.return_value = True
    target.run_table_fill()
    assert_preserved(target)


def test_thread_start_failure_preserves_queue_for_retry():
    target = app()
    with patch('src.orchestrator.threading.Thread') as worker:
        worker.return_value.start.side_effect = RuntimeError('no thread resources')
        target.run_table_fill()
    assert_preserved(target)
    assert target.state == OrchestratorState.IDLE
    assert target._typing_thread is None
