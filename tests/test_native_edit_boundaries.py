from unittest.mock import Mock

import pytest

import typing_profiler as module
from typing_profiler import KeyEvent, TypingAnalyzer, TypingRecorder, keyboard


@pytest.mark.parametrize('boundary', [
    keyboard.Key.left, keyboard.Key.right, keyboard.Key.home, keyboard.Key.end,
    keyboard.Key.delete, keyboard.Key.cmd, keyboard.Key.ctrl_r,
])
def test_recorder_breaks_timing_after_edits_and_shortcuts(monkeypatch, boundary):
    monkeypatch.setattr(module.time, 'monotonic', Mock(side_effect=[1, 2, 3, 4]))
    recorder = TypingRecorder()
    recorder._on_press(keyboard.KeyCode.from_char('a'))
    recorder._on_press(boundary)
    recorder._on_release(boundary)
    recorder._on_press(keyboard.KeyCode.from_char('b'))
    recorder._on_press(keyboard.KeyCode.from_char('c'))
    analyzer = TypingAnalyzer(recorder.events)
    analyzer._compute_intervals()
    analyzer._detect_pauses()
    assert set(analyzer.digraph_intervals) == {'bc'}
    assert analyzer.intervals == [1]
    assert [p.after_char for p in analyzer.pauses] == ['b']


def test_shift_keeps_timing_and_restart_clears_run_state(monkeypatch):
    monkeypatch.setattr(module.keyboard, 'Listener', Mock())
    recorder = TypingRecorder()
    recorder._on_press(keyboard.KeyCode.from_char('a'))
    recorder._on_press(keyboard.Key.shift)
    recorder._on_release(keyboard.Key.shift)
    recorder._on_press(keyboard.KeyCode.from_char('B'))
    analyzer = TypingAnalyzer(recorder.events)
    analyzer._compute_intervals()
    assert set(analyzer.digraph_intervals) == {'ab'}
    recorder._on_press(keyboard.Key.left)
    recorder.start()
    recorder._on_press(keyboard.KeyCode.from_char('c'))
    assert recorder.events[0].run_id == 0


def test_run_boundary_splits_backspaces_and_discards_unobserved_pause_times():
    events = [KeyEvent(0, 'x'), KeyEvent(.1, '<BS>', is_backspace=True),
              KeyEvent(1, '<BS>', is_backspace=True, run_id=1),
              KeyEvent(1.1, '<BS>', is_backspace=True, run_id=1),
              KeyEvent(2, 'y', run_id=2)]
    analyzer = TypingAnalyzer(events)
    analyzer._detect_corrections()
    assert [c.chars_deleted for c in analyzer.corrections] == [1, 2]
    first, second = analyzer.corrections
    assert first.pause_before == .1
    assert first.pause_after is None
    assert second.pause_before is None
    assert second.pause_after is None
    assert second.backspace_intervals == pytest.approx([.1])
    # Export must skip missing samples rather than treating an edit as a pause.
    analyzer._build_profile()


def test_bursts_and_word_rates_do_not_join_across_edits():
    events = [KeyEvent(i * .2, 's') for i in range(11)]
    events += [KeyEvent(2.05, 'a'), KeyEvent(2.1, 'b'),
               KeyEvent(3, 'c', run_id=1), KeyEvent(3.05, 'd', run_id=1),
               KeyEvent(3.1, 'e', run_id=1)]
    analyzer = TypingAnalyzer(events)
    analyzer._compute_intervals()
    analyzer._detect_bursts()
    assert analyzer.burst_lengths == []
    analyzer = TypingAnalyzer([KeyEvent(0, 'a'), KeyEvent(1, 'b', run_id=1),
                              KeyEvent(2, ' ', is_space=True, run_id=1)])
    analyzer._compute_word_wpms()
    assert analyzer.word_wpms == [12]


def test_pause_context_and_word_rates_restart_after_edits():
    events = [KeyEvent(0, '.'), KeyEvent(.1, ' ', is_space=True),
              KeyEvent(1, ' ', is_space=True, run_id=1),
              KeyEvent(2, 'a', run_id=1)]
    analyzer = TypingAnalyzer(events)
    analyzer._detect_pauses()
    assert [p.context for p in analyzer.pauses] == ['word_boundary']
    analyzer = TypingAnalyzer([KeyEvent(0, 'a'),
                              KeyEvent(.1, '<BS>', is_backspace=True),
                              KeyEvent(1, 'b'), KeyEvent(2, ' ', is_space=True)])
    analyzer._compute_word_wpms()
    assert analyzer.word_wpms == [12]
