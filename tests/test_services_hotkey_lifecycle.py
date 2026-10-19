from unittest.mock import Mock, patch
import pytest
from src.hotkey_listener import HotkeyListener, keyboard


def test_repeated_start_does_not_create_orphan_global_listener():
    listener = HotkeyListener()
    with patch("src.hotkey_listener.keyboard.Listener") as factory:
        factory.return_value.is_alive.return_value = True
        listener.start()
        listener.start()
        factory.assert_called_once()
        listener.stop()
        factory.return_value.stop.assert_called_once()
        assert listener._key_listener is None


def test_failed_start_cleans_partial_listener_and_allows_retry():
    listener = HotkeyListener()
    broken, healthy = Mock(), Mock()
    broken.start.side_effect = RuntimeError("accessibility unavailable")
    with patch("src.hotkey_listener.keyboard.Listener", side_effect=[broken, healthy]):
        with pytest.raises(RuntimeError):
            listener.start()
        broken.stop.assert_called_once()
        assert listener._key_listener is None
        listener.start()
        assert listener._key_listener is healthy


def test_restart_after_dead_listener_clears_old_modifier_and_suppression_state():
    listener = HotkeyListener()
    listener._key_listener = Mock()
    listener._key_listener.is_alive.return_value = False
    listener._on_press(keyboard.Key.shift_l)
    listener._on_press(keyboard.Key.f6)
    listener.suppress()
    with patch("src.hotkey_listener.keyboard.Listener"):
        listener.start()
    assert not listener._shift_pressed
    assert not listener._f6_down
    assert not listener._suppressed
