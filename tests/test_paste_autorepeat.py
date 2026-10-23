from unittest.mock import Mock

from src.hotkey_listener import HotkeyListener, keyboard
from test_hotkey_state import immediate_threads


def test_paste_autorepeat_dispatches_once_until_v_is_released():
    paste = Mock()
    listener = HotkeyListener(on_paste=paste)
    v = keyboard.KeyCode.from_char("v")
    listener._on_press(keyboard.Key.cmd)
    with immediate_threads():
        for _ in range(1000):
            listener._on_press(v)
        assert paste.call_count == 1
        listener._on_release(v)
        listener._on_press(v)
    assert paste.call_count == 2


def test_restart_discards_held_paste_state():
    listener = HotkeyListener()
    listener._on_press(keyboard.Key.cmd)
    listener._on_press(keyboard.KeyCode.from_char("v"))
    assert listener._v_down
    listener.stop()
    assert not listener._v_down
