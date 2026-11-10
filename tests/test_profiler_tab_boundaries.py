"""Native Tab may change focus; no destination text can be inferred from it."""
from unittest.mock import Mock

import pytest

import typing_profiler as native


def recording(monkeypatch):
    clock = Mock()
    monkeypatch.setattr(native.time, "monotonic", clock)
    recorder = native.TypingRecorder()

    def press(key, timestamp):
        clock.return_value = timestamp
        recorder._on_press(key)

    return recorder, press


def tab(recorder, press, timestamp, shifted):
    if shifted:
        press(native.keyboard.Key.shift, timestamp - .01)
    press(native.keyboard.Key.tab, timestamp)
    if shifted:
        recorder._on_release(native.keyboard.Key.shift)


@pytest.mark.parametrize("shifted", [False, True])
def test_tab_does_not_train_text_timings_word_speed_or_pause_context(monkeypatch, shifted):
    recorder, press = recording(monkeypatch)
    press(native.keyboard.KeyCode.from_char("a"), 1)
    tab(recorder, press, 1.2, shifted)
    press(native.keyboard.KeyCode.from_char("b"), 2.2)
    press(native.keyboard.Key.space, 3.2)

    assert [event.char for event in recorder.events] == ["a", "b", " "]
    assert recorder.events[0].run_id != recorder.events[1].run_id
    assert not recorder.events[1].is_shift
    analyzer = native.TypingAnalyzer(recorder.events)
    analyzer._compute_intervals()
    analyzer._compute_word_wpms()
    analyzer._detect_pauses()
    assert analyzer.intervals == pytest.approx([1])
    assert set(analyzer.digraph_intervals) == {"b "}
    assert analyzer.word_wpms == pytest.approx([12])
    assert [(pause.after_char, pause.context) for pause in analyzer.pauses] == [
        ("b", "word_boundary"),
    ]


@pytest.mark.parametrize("shifted", [False, True])
def test_tab_splits_corrections_and_discards_cross_field_latency(monkeypatch, shifted):
    recorder, press = recording(monkeypatch)
    press(native.keyboard.KeyCode.from_char("x"), 1)
    press(native.keyboard.Key.backspace, 1.1)
    tab(recorder, press, 2, shifted)
    press(native.keyboard.Key.backspace, 3)
    press(native.keyboard.Key.backspace, 3.05)
    press(native.keyboard.KeyCode.from_char("y"), 3.1)

    assert len(recorder.events) == 5
    analyzer = native.TypingAnalyzer(recorder.events)
    analyzer._detect_corrections()
    assert [correction.chars_deleted for correction in analyzer.corrections] == [1, 2]
    before, after = analyzer.corrections
    assert before.pause_before == pytest.approx(.1)
    assert before.pause_after is None
    assert before.backspace_intervals == []
    assert after.pause_before is None
    assert after.pause_after == pytest.approx(.05)
    assert after.backspace_intervals == pytest.approx([.05])


@pytest.mark.parametrize("shifted", [False, True])
def test_consecutive_tabs_record_no_text_and_next_field_resumes_measurement(monkeypatch, shifted):
    recorder, press = recording(monkeypatch)
    tab(recorder, press, 1, shifted)
    tab(recorder, press, 2, shifted)
    assert recorder.events == []
    press(native.keyboard.KeyCode.from_char("a"), 3)
    tab(recorder, press, 4, shifted)
    tab(recorder, press, 5, shifted)
    press(native.keyboard.KeyCode.from_char("b"), 6)
    press(native.keyboard.KeyCode.from_char("c"), 6.1)

    assert [event.char for event in recorder.events] == ["a", "b", "c"]
    assert recorder.events[0].run_id != recorder.events[1].run_id
    assert recorder.events[1].run_id == recorder.events[2].run_id
    analyzer = native.TypingAnalyzer(recorder.events)
    analyzer._compute_intervals()
    assert set(analyzer.digraph_intervals) == {"bc"}
    assert analyzer.intervals == pytest.approx([.1])
