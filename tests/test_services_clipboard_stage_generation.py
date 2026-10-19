"""Callback completion can only consume or retry the stage it launched."""
from unittest.mock import Mock

import pytest

from src.clipboard_monitor import ClipboardMonitor
from test_clipboard_probe import Item, Pasteboard
from test_clipboard_restore import pasteboard_patch


@pytest.mark.parametrize("new_copy", ["image", "empty", "whitespace"])
@pytest.mark.parametrize("accepted", [False, True])
def test_observed_nontext_copy_invalidates_inflight_stage(new_copy, accepted):
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor.enabled = True
        monitor._capture_change()
        def callback(_content):
            if new_copy == "image":
                pb.items = [Item({"png": b"new image"})]
                pb.revision += 1
            elif new_copy == "empty":
                pb.clearContents()
            else:
                pb.setString_forType_("  ", "text")
            monitor._capture_change()
            return accepted
        monitor._on_change = Mock(side_effect=callback)
        monitor.trigger_paste()
        assert monitor._staged_content is None
        assert monitor._saved_clipboard_items is None
        assert monitor._owned_empty_revision is None
        monitor.trigger_paste()
        assert monitor._on_change.call_count == 1


@pytest.mark.parametrize("accepted", [False, True])
def test_callback_completion_preserves_new_stage_and_its_restore_ownership(accepted):
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor.enabled = True
        monitor._capture_change()
        def callback(_content):
            pb.setString_forType_("new copy", "text")
            monitor._capture_change()
            return accepted
        monitor._on_change = callback
        monitor.trigger_paste()
        assert monitor._staged_content.text == "new copy"
        assert monitor._owned_empty_revision == pb.changeCount()
        assert monitor._saved_clipboard_items[0].data == {"text": b"new copy"}
        monitor.enabled = False
        assert pb.items[0].data == {"text": b"new copy"}


def test_rejected_launch_on_same_empty_revision_can_retry_then_transfer_ownership():
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock(side_effect=[False, True]))
    with pasteboard_patch(pb):
        monitor.enabled = True
        monitor._capture_change()
        staged = monitor._staged_content
        revision = monitor._owned_empty_revision
        monitor.trigger_paste()
        assert monitor._staged_content is staged
        assert monitor._owned_empty_revision == revision == pb.changeCount()
        monitor.trigger_paste()
        assert monitor._staged_content is None
        assert monitor._owned_empty_revision is None
        assert monitor._saved_clipboard_items is None
        assert monitor._on_change.call_count == 2
