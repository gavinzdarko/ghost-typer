from unittest.mock import patch
import pytest
from src.keystroke_simulator import KeystrokeSimulator, Key


def simulator():
    with patch('src.keystroke_simulator.Controller'):
        return KeystrokeSimulator()


def test_failed_main_key_releases_every_modifier():
    sim = simulator()
    sim._controller.press.side_effect = [None, None, RuntimeError('backend failed')]
    with patch('src.keystroke_simulator.time.sleep'):
        sim.hotkey('cmd', 'shift', 'b')
    released = [c.args[0] for c in sim._controller.release.call_args_list]
    assert released[-2:] == [Key.shift, Key.cmd]
    assert len(released) == 3


def test_failed_release_does_not_skip_remaining_modifiers():
    sim = simulator()
    sim._controller.release.side_effect = [RuntimeError('release failed'), None, None]
    with patch('src.keystroke_simulator.time.sleep'):
        sim.hotkey('cmd', 'shift', 'b')
    assert sim._controller.release.call_count == 3
    assert sim._controller.release.call_args.args == (Key.cmd,)


def test_special_key_release_attempted_after_partial_press_failure():
    sim = simulator()
    sim._controller.press.side_effect = RuntimeError('partial press')
    sim.press_key('enter')
    sim._controller.release.assert_called_once_with(Key.enter)
