from unittest.mock import Mock
from src.clipboard_monitor import ClipboardContent, ClipboardMonitor


def test_rejected_launch_keeps_staged_content_for_retry():
    callback = Mock(side_effect=[False, True])
    monitor = ClipboardMonitor(callback)
    monitor.enabled = True
    content = ClipboardContent('next session')
    monitor._staged_content = content
    monitor.trigger_paste()
    assert monitor._staged_content is content
    monitor.trigger_paste()
    assert monitor._staged_content is None
    assert callback.call_count == 2


def test_failed_callback_keeps_content_but_preserves_newer_copy():
    monitor = ClipboardMonitor(Mock(side_effect=RuntimeError('launch failed')))
    monitor.enabled = True
    content = ClipboardContent('retry')
    monitor._staged_content = content
    monitor.trigger_paste()
    assert monitor._staged_content is content
    newer = ClipboardContent('newer copy')
    def replace_and_reject(_content):
        monitor._staged_content = newer
        return False
    monitor._on_change = replace_and_reject
    monitor.trigger_paste()
    assert monitor._staged_content is newer
