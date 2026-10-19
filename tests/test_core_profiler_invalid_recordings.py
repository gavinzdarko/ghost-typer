import pytest

from typing_profiler import KeyEvent, TypingAnalyzer


@pytest.mark.parametrize("timestamps", [[0] * 10, [float("nan")] * 10,
    [0] + [float("inf")] * 9, list(reversed(range(10))),
    [0, 1, 2, 1, 4, 5, 6, 7, 8, 9]])
def test_invalid_recording_timestamps_fail_before_statistics(timestamps):
    analyzer = TypingAnalyzer([KeyEvent(t, "a") for t in timestamps])
    with pytest.raises(ValueError, match="timestamps"):
        analyzer.analyze()
    assert analyzer.intervals == []


def test_backspaces_alone_cannot_export_a_zero_speed_profile():
    with pytest.raises(ValueError, match="no typed characters"):
        TypingAnalyzer([KeyEvent(i, "<BS>", is_backspace=True) for i in range(10)]).analyze()


def test_insufficient_data_raises_an_actionable_library_error():
    with pytest.raises(ValueError, match="at least 10"):
        TypingAnalyzer([]).analyze()


def test_duplicate_timestamps_are_valid_when_recording_spans_time():
    profile = TypingAnalyzer([KeyEvent(i // 2, "a") for i in range(10)]).analyze()
    assert profile["analysis"]["session_duration_sec"] == 4
