from test_clipboard_probe import Pasteboard
from test_clipboard_restore import pasteboard_patch
from src.clipboard_monitor import ClipboardMonitor
from unittest.mock import Mock


def test_new_copy_during_read_is_never_cleared_or_staged():
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        pb.on_read = lambda: pb.setString_forType_('newer copy', 'text')
        monitor._capture_change(pb.changeCount())
    assert pb.items[0].data == {'text': b'newer copy'}
    assert monitor._staged_content is None


def test_new_copy_during_snapshot_is_not_cleared():
    pb = Pasteboard()
    original_items = pb.pasteboardItems
    def race():
        items = original_items()
        pb.setString_forType_('newer copy', 'text')
        return items
    pb.pasteboardItems = race
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor._capture_change(pb.changeCount())
    assert pb.items[0].data == {'text': b'newer copy'}
    assert monitor._staged_content is None


def test_clear_revision_does_not_claim_a_later_writer():
    class RacePasteboard(Pasteboard):
        def clearContents(self):
            super().clearContents()
            written = self.revision
            self.setString_forType_('newer copy', 'text')
            return written
    pb = RacePasteboard()
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor.enabled = True
        monitor._capture_change(pb.changeCount())
        assert monitor._owned_empty_revision < pb.changeCount()
        monitor.enabled = False
    assert pb.items[0].data == {'text': b'newer copy'}


def test_nontext_copy_supersedes_old_staged_text():
    pb = Pasteboard()
    monitor = ClipboardMonitor(Mock())
    with pasteboard_patch(pb):
        monitor._capture_change()
        pb.clearContents()
        monitor._capture_change()
    assert monitor._staged_content is None


def test_paste_before_poll_never_launches_an_older_staged_copy():
    pb = Pasteboard()
    callback = Mock(return_value=True)
    monitor = ClipboardMonitor(callback)
    with pasteboard_patch(pb):
        monitor.enabled = True
        monitor._capture_change()
        pb.setString_forType_('new user copy', 'text')
        monitor.trigger_paste()
        callback.assert_not_called()
        assert monitor._staged_content is None
        assert monitor._saved_clipboard_items is None
        monitor.enabled = False
    assert pb.items[0].data == {'text': b'new user copy'}


def test_image_copy_before_poll_also_invalidates_staged_paste():
    pb = Pasteboard()
    callback = Mock()
    monitor = ClipboardMonitor(callback)
    with pasteboard_patch(pb):
        monitor.enabled = True
        monitor._capture_change()
        pb.clearContents()
        monitor.trigger_paste()
    callback.assert_not_called()
    assert monitor._staged_content is None
