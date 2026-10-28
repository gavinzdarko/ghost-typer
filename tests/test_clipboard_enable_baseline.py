"""Turning ON observes future copies without consuming clipboard history."""
from unittest.mock import Mock, patch

import pytest

from src.clipboard_monitor import ClipboardMonitor
from test_clipboard_probe import Pasteboard
from test_clipboard_restore import pasteboard_patch


def poll_once(monitor):
    monitor._stop_event.clear()
    with patch.object(monitor._stop_event, "wait", side_effect=lambda **_: monitor._stop_event.set()):
        monitor._monitor_loop()


@pytest.mark.parametrize("immediate", [False, True])
def test_enable_preserves_off_copy_then_accepts_next_copy(immediate):
    pb = Pasteboard()
    accepted = Mock(return_value=True)
    monitor = ClipboardMonitor(accepted)
    monitor._immediate_mode = immediate
    with pasteboard_patch(pb):
        monitor._last_change_count = pb.changeCount()
        pb.setString_forType_("copied while off", "text")
        old_revision = pb.changeCount()
        monitor.enabled = True
        poll_once(monitor)
        assert pb.changeCount() == old_revision
        assert pb.stringForType_("text") == "copied while off"
        assert monitor._staged_content is None
        accepted.assert_not_called()

        pb.setString_forType_("copied while on", "text")
        poll_once(monitor)
        assert not pb.items
        if not immediate:
            assert monitor._staged_content.text == "copied while on"
            monitor.trigger_paste()
        accepted.assert_called_once()
        assert accepted.call_args.args[0].text == "copied while on"


def test_repeated_enable_does_not_skip_a_new_copy_waiting_for_poll():
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor.enabled = True
        pb.setString_forType_("new copy", "text")
        monitor.enabled = True
        poll_once(monitor)
        assert monitor._staged_content.text == "new copy"


def test_reenable_leaves_the_restored_stage_on_the_clipboard():
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor.enabled = True
        pb.setString_forType_("unused copy", "text")
        poll_once(monitor)
        monitor.enabled = False
        assert pb.stringForType_("text") == "unused copy"
        monitor.enabled = True
        poll_once(monitor)
        assert pb.stringForType_("text") == "unused copy"
        assert monitor._staged_content is None
