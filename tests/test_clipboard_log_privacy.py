import logging
from unittest.mock import Mock

from src.clipboard_monitor import ClipboardContent, ClipboardMonitor


def test_staged_paste_logs_metadata_without_clipboard_text(caplog):
    monitor = ClipboardMonitor(Mock(return_value=True))
    monitor.enabled = True
    monitor._staged_content = ClipboardContent('secret password account details')
    with caplog.at_level(logging.INFO):
        monitor.trigger_paste()
    assert 'secret password' not in caplog.text
    assert '31 characters' in caplog.text


def test_capture_logs_do_not_contain_copied_text(caplog):
    from test_clipboard_probe import Pasteboard
    from test_clipboard_restore import pasteboard_patch
    pb = Pasteboard()
    pb.setString_forType_('private copied content', 'text')
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb), caplog.at_level(logging.INFO):
        monitor._capture_change()
    assert 'private copied content' not in caplog.text
    assert '22 characters' in caplog.text
