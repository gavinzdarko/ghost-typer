from types import SimpleNamespace
from unittest.mock import Mock, patch
from src.hotkey_listener import HotkeyListener, keyboard


def immediate_threads():
    return patch('src.hotkey_listener.threading.Thread',
                 side_effect=lambda target, daemon: SimpleNamespace(start=target))


def test_releasing_one_shift_keeps_other_shift_active_for_emergency_stop():
    stop = Mock()
    pause = Mock()
    listener = HotkeyListener(on_emergency_stop=stop, on_toggle_pause=pause)
    listener._on_press(keyboard.Key.shift_l)
    listener._on_press(keyboard.Key.shift_r)
    listener._on_release(keyboard.Key.shift_l)
    with immediate_threads():
        listener._on_press(keyboard.Key.f6)
    stop.assert_called_once()
    pause.assert_not_called()


def test_f6_repeat_dispatches_once_until_release():
    pause = Mock()
    listener = HotkeyListener(on_toggle_pause=pause)
    with immediate_threads():
        listener._on_press(keyboard.Key.f6)
        listener._on_press(keyboard.Key.f6)
        listener._on_press(keyboard.Key.f6)
        assert pause.call_count == 1
        listener._on_release(keyboard.Key.f6)
        listener._on_press(keyboard.Key.f6)
    assert pause.call_count == 2


def test_ctrl_f6_turns_off_while_typing_instead_of_pausing():
    toggle, pause = Mock(), Mock()
    listener = HotkeyListener(on_toggle_enabled=toggle, on_toggle_pause=pause)
    listener.suppress()
    listener._on_press(keyboard.Key.ctrl_l)
    with immediate_threads():
        listener._on_press(keyboard.Key.f6)
    toggle.assert_called_once()
    pause.assert_not_called()


def test_stop_clears_modifier_and_repeat_state_before_restart():
    listener = HotkeyListener()
    listener._on_press(keyboard.Key.cmd_l)
    listener._on_press(keyboard.Key.f6)
    listener.stop()
    assert not listener._cmd_pressed
    assert not listener._f6_down
