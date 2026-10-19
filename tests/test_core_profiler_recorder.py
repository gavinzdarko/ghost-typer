from unittest.mock import Mock

import pytest

import typing_profiler as module
from typing_profiler import TypingRecorder, keyboard


@pytest.mark.parametrize("modifier", [keyboard.Key.cmd, keyboard.Key.cmd_r,
                                      keyboard.Key.ctrl, keyboard.Key.ctrl_r])
def test_shortcut_letters_do_not_train_typing_profile(modifier):
    recorder = TypingRecorder()
    recorder._on_press(modifier)
    recorder._on_press(keyboard.KeyCode.from_char("v"))
    recorder._on_press(keyboard.Key.backspace)
    recorder._on_release(modifier)
    recorder._on_press(keyboard.KeyCode.from_char("a"))
    assert [event.char for event in recorder.events] == ["a"]


def test_releasing_one_shift_keeps_other_shift_held():
    recorder = TypingRecorder()
    recorder._on_press(keyboard.Key.shift_l)
    recorder._on_press(keyboard.Key.shift_r)
    recorder._on_release(keyboard.Key.shift_l)
    recorder._on_press(keyboard.KeyCode.from_char("A"))
    assert recorder.events[-1].is_shift
    recorder._on_release(keyboard.Key.shift_r)
    recorder._on_press(keyboard.KeyCode.from_char("a"))
    assert not recorder.events[-1].is_shift


def test_recorder_uses_monotonic_time_and_restarts_cleanly(monkeypatch):
    monkeypatch.setattr(module.time, "time", Mock(side_effect=AssertionError("wall clock")))
    monkeypatch.setattr(module.time, "monotonic", Mock(side_effect=[10, 11, 12, 20, 21]))
    monkeypatch.setattr(module.keyboard, "Listener", Mock())
    recorder = TypingRecorder()
    recorder.start()
    recorder._on_press(keyboard.KeyCode.from_char("a"))
    recorder._on_press(keyboard.Key.cmd)
    recorder.stop()
    recorder.start()
    recorder._on_press(keyboard.KeyCode.from_char("b"))
    assert not recorder.is_done
    assert [event.timestamp for event in recorder.events] == [21]
    assert [event.char for event in recorder.events] == ["b"]
