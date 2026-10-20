from unittest.mock import patch
import pytest

from src.keystroke_simulator import KeystrokeError, KeystrokeSimulator, Key


@pytest.mark.parametrize('raw', [False, True])
def test_character_release_attempted_after_partial_key_down_failure(raw):
    with patch('src.keystroke_simulator.Controller'):
        sim = KeystrokeSimulator()
    sim._controller.press.side_effect = RuntimeError('failed after posting key down')
    with pytest.raises(KeystrokeError):
        if raw:
            sim.type_string_raw('hello')
        else:
            sim.type_char('h')
    sim._controller.press.assert_called_once_with('h')
    sim._controller.release.assert_called_once_with('h')
    assert not sim.is_active


@pytest.mark.parametrize('char,key', [('A', 'A'), ('é', 'é'), ('😀', '😀'), ('\n', Key.enter), ('\r', Key.enter), ('\t', Key.tab)])
def test_characters_keep_pynput_native_mapping_and_unicode(char, key):
    with patch('src.keystroke_simulator.Controller'):
        sim = KeystrokeSimulator()
    sim.type_char(char)
    sim._controller.press.assert_called_once_with(key)
    sim._controller.release.assert_called_once_with(key)
    assert sim.is_active
