from unittest.mock import Mock

from src.clipboard_monitor import ClipboardContent
from src.orchestrator import _ROW_BREAK
from test_table_retention import app, run


def test_reentering_table_mode_keeps_failed_work_and_row_boundaries():
    target = app()
    target._execute_plan.side_effect = RuntimeError('keyboard unavailable')
    run(target, ['first', _ROW_BREAK, 'second'])
    retained = list(target._table_queue)
    target.on_table_queue_change = Mock()
    target.enable_table_fill()
    assert target._table_queue == retained
    assert target.table_fill_mode
    assert target.clipboard_monitor._immediate_mode
    target.on_table_queue_change.assert_called_once_with(2)
    target._add_to_table_queue(ClipboardContent('third'))
    assert [item.text for item in target._table_queue] == ['first', _ROW_BREAK, 'second', 'third']


def test_repeated_enable_does_not_discard_queued_work():
    target = app()
    target.enable_table_fill()
    target._add_to_table_queue(ClipboardContent('one'))
    target.enable_table_fill()
    assert target.table_queue_count() == 1
