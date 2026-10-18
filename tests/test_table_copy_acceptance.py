from unittest.mock import Mock

import pytest

from src.clipboard_monitor import ClipboardMonitor
from test_clipboard_probe import Pasteboard
from test_clipboard_restore import pasteboard_patch


@pytest.mark.parametrize('failure', [False, RuntimeError('queue failed')])
def test_rejected_table_copy_keeps_all_clipboard_representations(failure):
    pb = Pasteboard()
    expected = dict(pb.items[0].data)
    callback = Mock(return_value=failure)
    if isinstance(failure, Exception):
        callback.side_effect = failure
    monitor = ClipboardMonitor(callback)
    monitor._immediate_mode = True
    with pasteboard_patch(pb):
        monitor._capture_change()
    assert pb.items[0].data == expected


def test_accepted_table_copy_does_not_clear_a_new_user_revision():
    pb = Pasteboard()
    monitor = ClipboardMonitor(lambda content: pb.setString_forType_('new copy', 'text'))
    monitor._immediate_mode = True
    with pasteboard_patch(pb):
        monitor._capture_change()
    assert pb.items[0].data == {'text': b'new copy'}


def test_accepted_table_copy_is_cleared_after_callback():
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock(return_value=True))
    monitor._immediate_mode = True
    with pasteboard_patch(pb):
        monitor._capture_change()
    assert not pb.items
