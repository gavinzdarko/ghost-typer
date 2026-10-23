import pytest

from typing_profiler import KeyEvent, TypingAnalyzer


def recording(times, text):
    return [KeyEvent(time, char, is_space=char == " ", is_enter=char == "\n")
            for time, char in zip(times, text)]


def test_short_recording_counts_unfinished_final_word_in_session_speed():
    events = recording([0, 1, *[1 + i / 10 for i in range(1, 9)]], "a bcdefghi")
    result = TypingAnalyzer(events).analyze()
    expected = len(events) / 5 / (1.8 / 60)
    assert result["analysis"]["avg_wpm"] == pytest.approx(round(expected, 1))
    assert result["ghost_typer_settings"]["wpm"] == round(expected)


def test_session_speed_includes_recording_tail_after_last_complete_window():
    events = recording(list(range(13)), "a b c d e f g")
    result = TypingAnalyzer(events).analyze()
    assert result["analysis"]["avg_wpm"] == 13
    assert result["ghost_typer_settings"]["wpm"] == 13
