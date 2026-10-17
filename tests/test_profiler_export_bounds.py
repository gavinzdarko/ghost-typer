from src.models import Settings
from typing_profiler import KeyEvent, TypingAnalyzer


def event(timestamp, char):
    return KeyEvent(timestamp, char, is_backspace=char == "<BS>",
                    is_space=char == " ", is_enter=char == "\n")


def test_long_correction_exports_ordered_notice_delay_limits():
    events = [event(i * .1, char) for i, char in enumerate("abcdefghijklmno")]
    events += [event(1.5 + i * .1, "<BS>") for i in range(13)]
    events += [event(2.8 + i * .1, char) for i, char in enumerate("other words here ")]
    settings = TypingAnalyzer(events).analyze()["ghost_typer_settings"]
    assert settings["correction_delay_chars_min"] == settings["correction_delay_chars_max"] == 12
    loaded = Settings.from_dict(settings)
    assert loaded.correction_delay_chars_min <= loaded.correction_delay_chars_max


def test_sparse_long_thinking_pauses_never_invert_exported_duration_range():
    events = [event(i * .1, char) for i, char in enumerate("some words here ")]
    events += [event(7.5 + i * .1, char) for i, char in enumerate("more words after ")]
    settings = TypingAnalyzer(events).analyze()["ghost_typer_settings"]
    assert settings["pause_duration_min"] == settings["pause_duration_max"] == 6


def test_regular_sample_preserves_measured_and_default_ranges():
    events = [event(i * .1, char) for i, char in enumerate("some ordinary typing words here ")]
    settings = TypingAnalyzer(events).analyze()["ghost_typer_settings"]
    assert (settings["pause_duration_min"], settings["pause_duration_max"]) == (.3, 4)
    for name in ("correction_delay_chars", "pause_duration", "burst_length", "sentence_pause", "paragraph_pause"):
        assert settings[name + "_min"] <= settings[name + "_max"]
