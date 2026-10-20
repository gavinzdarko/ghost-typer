import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent, ClipboardMonitor


class Item:
    def __init__(self, data=None):
        self.data = dict(data or {})
    @classmethod
    def alloc(cls):
        return cls()
    def init(self):
        return self
    def types(self):
        return list(self.data)
    def dataForType_(self, kind):
        return self.data[kind]
    def setData_forType_(self, value, kind):
        self.data[kind] = value
        return True


class Pasteboard:
    def __init__(self):
        self.items = [Item({'text': b'original', 'html': b'<b>original</b>', 'png': b'\x89PNG'})]
        self.revision = 10
        self.on_read = None
    def pasteboardItems(self):
        return self.items
    def clearContents(self):
        self.items = []
        self.revision += 1
    def setString_forType_(self, value, kind):
        self.items = [Item({kind: value.encode()})]
        self.revision += 1
        return True
    def changeCount(self):
        return self.revision
    def stringForType_(self, kind):
        result = self.items[0].data.get(kind, b'').decode() if self.items else ''
        if self.on_read:
            self.on_read()
        return result
    def writeObjects_(self, items):
        self.items = items
        self.revision += 1
        return True


def probe(pb, simulator):
    app = Orchestrator.__new__(Orchestrator)
    app.clipboard_monitor = ClipboardMonitor(Mock())
    app.clipboard_monitor.enabled = True
    app._cancel_event = __import__('threading').Event()
    fake_appkit = SimpleNamespace(NSPasteboard=SimpleNamespace(generalPasteboard=lambda: pb), NSPasteboardItem=Item, NSPasteboardTypeString='text')
    return app, patch.dict(sys.modules, {'AppKit': fake_appkit})


def test_probe_restores_all_types_and_preserves_user_off():
    pb = Pasteboard()
    sim = Mock()
    app, context = probe(pb, sim)
    sim.hotkey.side_effect = lambda *keys: pb.setString_forType_('cell', 'text') if keys == ('command', 'c') else None
    sim.wait.side_effect = lambda delay: setattr(app.clipboard_monitor, 'enabled', False)
    with context:
        assert app._cell_has_content(sim)
    assert pb.items[0].data == {'text': b'original', 'html': b'<b>original</b>', 'png': b'\x89PNG'}
    assert not app.clipboard_monitor.enabled
    assert sim.hotkey.call_args_list[0].args == ('command', 'left')
    assert sim.hotkey.call_args_list[1].args == ('command', 'shift', 'right')
    sim.press_key.assert_not_called()
    assert app.clipboard_monitor._suspensions == 0
    assert app.clipboard_monitor._last_change_count == pb.changeCount()


def test_probe_failure_restores_clipboard_and_releases_suspension():
    pb = Pasteboard()
    sim = Mock()
    sim.hotkey.side_effect = RuntimeError('key failure')
    app, context = probe(pb, sim)
    with context, pytest.raises(RuntimeError, match='key failure'):
        app._cell_has_content(sim)
    assert 'png' in pb.items[0].data
    assert app.clipboard_monitor.enabled
    assert app.clipboard_monitor._suspensions == 0


def test_new_user_copy_after_probe_response_is_not_overwritten():
    pb = Pasteboard()
    sim = Mock()
    sim.hotkey.side_effect = lambda *keys: pb.setString_forType_('cell', 'text') if keys == ('command', 'c') else None
    pb.on_read = lambda: pb.setString_forType_('user copy', 'text')
    app, context = probe(pb, sim)
    with context, pytest.raises(RuntimeError, match='Clipboard changed'):
        app._cell_has_content(sim)
    assert pb.items[0].data == {'text': b'user copy'}
    assert app.clipboard_monitor._suspensions == 0


def test_suspension_does_not_consume_staged_paste_or_change_enabled():
    monitor = ClipboardMonitor(Mock())
    monitor.enabled = True
    monitor._staged_content = ClipboardContent('staged')
    with monitor.suspended():
        monitor.trigger_paste()
        assert monitor.enabled
        assert monitor._staged_content.text == 'staged'
    monitor.trigger_paste()
    monitor._on_change.assert_called_once()


def test_new_copy_during_snapshot_is_preserved_without_sending_keys():
    pb = Pasteboard()
    original_items = pb.pasteboardItems
    def copying_snapshot():
        result = original_items()
        pb.setString_forType_('new user copy', 'text')
        return result
    pb.pasteboardItems = copying_snapshot
    sim = Mock()
    app, context = probe(pb, sim)
    with context, pytest.raises(RuntimeError, match='Clipboard changed'):
        app._cell_has_content(sim)
    assert pb.items[0].data == {'text': b'new user copy'}
    sim.hotkey.assert_not_called()


def test_clear_revision_does_not_claim_a_new_user_copy():
    pb = Pasteboard()
    original_clear = pb.clearContents
    def concurrent_clear():
        original_clear()
        our_revision = pb.changeCount()
        pb.setString_forType_('new user copy', 'text')
        return our_revision
    pb.clearContents = concurrent_clear
    sim = Mock()
    app, context = probe(pb, sim)
    with context, pytest.raises(RuntimeError, match='Clipboard changed'):
        app._cell_has_content(sim)
    assert pb.items[0].data == {'text': b'new user copy'}
    sim.hotkey.assert_not_called()
