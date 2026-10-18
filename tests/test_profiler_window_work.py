from typing_profiler import KeyEvent, TypingAnalyzer


def reference(events):
    typed = [e for e in events if not e.is_backspace]
    if len(typed) < 5:
        return []
    values = []
    t = typed[0].timestamp
    while t + 10 <= typed[-1].timestamp:
        count = sum(t <= e.timestamp < t + 10 and len(e.char) == 1 for e in typed)
        values.append(count * 1.2)
        t += 5
    return values


def test_sliding_windows_match_existing_half_open_boundary_semantics():
    import pytest
    events = [KeyEvent(i * .5, 'a' if i % 4 else 'backspace', is_backspace=i % 4 == 0)
              for i in range(101)]
    analyzer = TypingAnalyzer(events)
    analyzer._compute_rolling_wpm()
    assert analyzer.rolling_wpms == pytest.approx(reference(events))


def test_long_recording_reads_each_timestamp_a_bounded_number_of_times():
    reads = [0]
    class Event:
        is_backspace = False
        char = 'a'
        def __init__(self, timestamp):
            self._timestamp = timestamp
        @property
        def timestamp(self):
            reads[0] += 1
            return self._timestamp
    events = [Event(i * .1) for i in range(10_000)]
    analyzer = TypingAnalyzer(events)
    analyzer._compute_rolling_wpm()
    assert len(analyzer.rolling_wpms) == 198
    assert reads[0] < 5 * len(events)
