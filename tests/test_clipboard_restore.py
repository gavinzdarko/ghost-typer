from unittest.mock import Mock, patch
from src.clipboard_monitor import ClipboardMonitor
from test_clipboard_probe import Item, Pasteboard


def capture(pb):
    monitor = ClipboardMonitor(Mock(return_value=True))
    monitor.enabled = True
    monitor._capture_change()
    return monitor


def pasteboard_patch(pb):
    return patch.multiple('src.clipboard_monitor', NSPasteboard=Mock(generalPasteboard=lambda: pb),
                          NSPasteboardItem=Item, NSPasteboardTypeString='text', NSPasteboardTypeHTML='html')


def test_off_restores_all_staged_clipboard_types():
    pb = Pasteboard()
    expected = dict(pb.items[0].data)
    with pasteboard_patch(pb):
        monitor = capture(pb)
        assert not pb.items
        monitor.enabled = False
        assert pb.items[0].data == expected
        assert monitor._staged_content is None


def test_stop_restores_stage_but_never_overwrites_a_newer_copy():
    pb = Pasteboard()
    with pasteboard_patch(pb):
        monitor = capture(pb)
        pb.setString_forType_('new user copy', 'text')
        monitor.stop()
        assert pb.items[0].data == {'text': b'new user copy'}


def test_accepted_paste_is_not_restored_at_shutdown():
    pb = Pasteboard()
    with pasteboard_patch(pb):
        monitor = capture(pb)
        monitor.trigger_paste()
        monitor.stop()
        assert not pb.items


def test_restore_failure_does_not_prevent_turning_off():
    pb = Pasteboard()
    with pasteboard_patch(pb):
        monitor = capture(pb)
        pb.writeObjects_ = Mock(side_effect=RuntimeError('pasteboard unavailable'))
        monitor.enabled = False
        assert not monitor.enabled
