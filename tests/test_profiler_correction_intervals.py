import pytest

from typing_profiler import KeyEvent, TypingAnalyzer


def test_correction_time_is_not_a_normal_digraph_or_thinking_pause():
    events = [KeyEvent(0, 'a'), KeyEvent(.1, 'x'),
              KeyEvent(.7, 'backspace', is_backspace=True),
              KeyEvent(1.2, 'b'), KeyEvent(1.3, 'c')]
    analyzer = TypingAnalyzer(events)
    analyzer._compute_intervals()
    analyzer._detect_pauses()
    analyzer._detect_corrections()
    assert analyzer.intervals == pytest.approx([.1, .1])
    assert set(analyzer.digraph_intervals) == {'ax', 'bc'}
    assert analyzer.pauses == []
    assert len(analyzer.corrections) == 1
    assert analyzer.corrections[0].pause_before == pytest.approx(.6)
    assert analyzer.corrections[0].pause_after == pytest.approx(.5)


def test_nonpositive_intervals_do_not_become_typing_speed_samples():
    analyzer = TypingAnalyzer([KeyEvent(1, 'a'), KeyEvent(1, 'b'),
                              KeyEvent(.5, 'c'), KeyEvent(.6, 'd')])
    analyzer._compute_intervals()
    assert analyzer.intervals == pytest.approx([.1])


def test_short_fast_runs_do_not_join_across_a_backspace_correction():
    events = [KeyEvent(i * .2, 's') for i in range(11)]
    events += [KeyEvent(2.05, 'a'), KeyEvent(2.1, 'b'),
               KeyEvent(2.5, 'backspace', is_backspace=True),
               KeyEvent(3, 'c'), KeyEvent(3.05, 'd'), KeyEvent(3.1, 'e')]
    analyzer = TypingAnalyzer(events)
    analyzer._compute_intervals()
    analyzer._detect_bursts()
    assert analyzer.burst_lengths == []


def test_actual_contiguous_fast_burst_is_still_detected_after_correction():
    events = [KeyEvent(i * .2, 's') for i in range(11)]
    events += [KeyEvent(2.5, 'backspace', is_backspace=True)]
    events += [KeyEvent(3 + i * .05, 'f') for i in range(5)]
    analyzer = TypingAnalyzer(events)
    analyzer._compute_intervals()
    analyzer._detect_bursts()
    assert analyzer.burst_lengths == [4]
