"""A copy admitted before table mode exits must keep clipboard ownership."""
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from src.clipboard_monitor import ClipboardContent
from test_clipboard_probe import Pasteboard
from test_clipboard_restore import pasteboard_patch
from test_table_retention import app


@pytest.mark.parametrize('exit_mode', ['disable', 'run'])
def test_table_copy_waiting_for_admission_survives_mode_exit(exit_mode):
    target = app()
    target.enable_table_fill()
    assert target._on_clipboard_change(ClipboardContent('queued')) is True
    target._launch_pipeline = Mock(return_value=True)
    target.on_table_queue_change = Mock()
    monitor = target.clipboard_monitor
    pb = Pasteboard()
    expected = dict(pb.items[0].data)
    entered, release = Event(), Event()
    add = target._add_to_table_queue

    def delayed_add(content):
        entered.set()
        assert release.wait(2), 'table copy was not released'
        return add(content)

    monitor._on_immediate_change = delayed_add
    monitor._on_change = Mock(side_effect=target._on_clipboard_change)
    with pasteboard_patch(pb):
        worker = Thread(target=monitor._capture_change)
        worker.start()
        try:
            assert entered.wait(2), 'table copy never reached admission'
            if exit_mode == 'disable':
                target.disable_table_fill()
            else:
                assert target.run_table_fill() is True
            release.set()
            worker.join(2)
            assert not worker.is_alive()
        finally:
            release.set()
            worker.join(2)
        assert pb.items[0].data == expected
    assert target.table_queue_count() == 0
    assert not target.table_fill_mode
    assert not monitor._immediate_mode
    target.on_table_queue_change.assert_called_once_with(0)
    assert target._launch_pipeline.call_count == (exit_mode == 'run')
    monitor._on_change.assert_not_called()


def test_table_queue_rejects_a_copy_when_mode_is_inactive():
    target = app()
    target.on_table_queue_change = Mock()
    assert target._add_to_table_queue(ClipboardContent('late copy')) is False
    assert target.table_queue_count() == 0
    target.on_table_queue_change.assert_not_called()


def test_active_table_copy_transfers_ownership_and_reports_acceptance():
    target = app()
    target.enable_table_fill()
    assert target._on_clipboard_change(ClipboardContent('first\nsecond')) is True
    assert [item.text for item in target._table_queue] == ['first', 'second']
