from unittest.mock import Mock, patch
from test_table_retention import app, run
from src.orchestrator import _ROW_BREAK
from src.clipboard_monitor import ClipboardContent


def test_row_break_skips_configured_label_columns_without_document_navigation():
    target = app()
    events = []
    sim = Mock(is_active=True)
    sim.press_key.side_effect = lambda key: events.append(('key', key))
    target._execute_plan.side_effect = lambda *args: events.append(('type', None))
    items = [ClipboardContent(item) for item in ('a', 'b', _ROW_BREAK, 'c', 'd')]
    with patch('src.orchestrator.KeystrokeSimulator', return_value=sim):
        target._table_fill_pipeline(items, skip_columns=2)
    assert events == [('type', None), ('key', 'tab'), ('type', None),
                      ('key', 'tab'), ('key', 'tab'), ('key', 'tab'), ('type', None),
                      ('key', 'tab'), ('type', None)]
    assert not target._table_queue
    target.notification_service.notify_complete.assert_called_once()


def test_untyped_row_break_and_following_cells_survive_cancellation():
    target = app()
    target._execute_plan.side_effect = lambda *args: target._cancel_event.set()
    run(target, ['a', _ROW_BREAK, 'b'])
    assert [item.text for item in target._table_queue] == ['a', _ROW_BREAK, 'b']


def test_row_skip_is_not_repeated_when_filled_cell_is_encountered():
    target = app()
    target._cell_has_content.side_effect = [False, True, False]
    sim = Mock(is_active=True)
    with patch('src.orchestrator.KeystrokeSimulator', return_value=sim):
        target._table_fill_pipeline([ClipboardContent(item) for item in ('a', _ROW_BREAK, 'b')], skip_columns=2)
    assert [call.args[0] for call in sim.press_key.call_args_list] == ['tab', 'tab', 'tab', 'right', 'tab']
    assert not target._table_queue
