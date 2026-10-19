from unittest.mock import Mock
import pytest
from src.clipboard_monitor import ClipboardContent, ClipboardMonitor
from test_clipboard_restore import pasteboard_patch
from test_clipboard_probe import Pasteboard


@pytest.mark.parametrize("reenable", [False, True])
def test_rejected_callback_cannot_resurrect_stage_after_off(reenable):
    monitor = ClipboardMonitor(Mock())
    monitor.enabled = True
    monitor._staged_content = ClipboardContent("old copy")
    def reject(_content):
        monitor.enabled = False
        if reenable:
            monitor.enabled = True
        return False
    monitor._on_change = Mock(side_effect=reject)
    monitor.trigger_paste()
    assert monitor._staged_content is None
    monitor.trigger_paste()
    assert monitor._on_change.call_count == 1


def test_new_user_copy_during_rejection_does_not_leave_an_old_retry():
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock())
    monitor.enabled = True
    with pasteboard_patch(pb):
        monitor._capture_change()
        def reject(_content):
            pb.setString_forType_("new copy", "text")
            return False
        monitor._on_change = reject
        monitor.trigger_paste()
        assert monitor._staged_content is None
        assert pb.stringForType_("text") == "new copy"


def test_off_during_failed_launch_still_restores_captured_representations():
    pb = Pasteboard()
    expected = dict(pb.items[0].data)
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor.enabled = True
        monitor._capture_change()
        def reject(_content):
            monitor.enabled = False
            raise RuntimeError("launch failed")
        monitor._on_change = reject
        monitor.trigger_paste()
        assert pb.items[0].data == expected
        assert monitor._staged_content is None
