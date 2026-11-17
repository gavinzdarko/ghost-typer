"""Recorded thinking-pause density must survive default-profile playback."""
import pytest

from src.models import Settings
from src.typing_engine import TypingEngine
from typing_profiler import KeyEvent, TypingAnalyzer


def recording(word_length=10, paused_spaces=()):
    text = " ".join(["a" * word_length] * 100)
    events = []
    timestamp = 0
    space_index = 0
    for char in text:
        timestamp += .1
        if char == " ":
            if space_index in paused_spaces:
                timestamp += 1
            space_index += 1
        events.append(KeyEvent(timestamp, char, is_space=char == " "))
    return TypingAnalyzer(events).analyze()


@pytest.mark.parametrize("word_length", [1, 10, 30])
def test_recorded_pause_density_matches_default_playback_independent_of_word_length(word_length):
    result = recording(word_length, range(0, 99, 20))
    settings = Settings.from_dict(result["ghost_typer_settings"])
    engine = TypingEngine(settings)
    assert result["analysis"]["thinking_pause_count"] == 5
    # An independent stratified draw sequence gives exactly five pauses over
    # the same 99 opportunities. It catches both per-character normalization
    # and forgetting the persona's probability factor without flaky sampling.
    draws = iter((index + .5) / 99 for index in range(99))
    engine._rng.random = lambda: next(draws)
    assert sum(engine.should_thinking_pause() for _ in range(99)) == 5
    expected = 99 * settings.pause_frequency * engine.profile.pauses.thinking_pause_probability_factor
    assert expected == pytest.approx(5, abs=.0005)


def test_unrepresentable_high_density_saturates_without_losing_measurement():
    result = recording(paused_spaces=range(99))
    assert result["analysis"]["thinking_pause_count"] == 99
    assert result["ghost_typer_settings"]["pause_frequency"] == 1
    assert Settings.from_dict(result["ghost_typer_settings"]).pause_frequency == 1


def test_no_observed_thinking_pauses_exports_zero():
    assert recording()["ghost_typer_settings"]["pause_frequency"] == 0


def test_no_space_opportunities_preserves_midword_pause_measurement_without_inventing_frequency():
    events = [KeyEvent(index * .1 + (1 if index >= 10 else 0), "a") for index in range(20)]
    result = TypingAnalyzer(events).analyze()
    assert result["analysis"]["thinking_pause_count"] == 1
    assert result["ghost_typer_settings"]["pause_frequency"] == 0


def test_space_after_unmeasured_boundary_is_not_a_recorded_pause_opportunity():
    events = [KeyEvent(index * .1, "a") for index in range(20)]
    # These spaces begin new runs, so their gaps are not measured.
    events += [KeyEvent(3, " ", is_space=True, run_id=1),
               KeyEvent(3.1, "b", run_id=1),
               KeyEvent(4, " ", is_space=True, run_id=2)]
    # One measured boundary with one thinking pause: frequency saturates.
    events += [KeyEvent(5, " ", is_space=True, run_id=2),
               KeyEvent(5.1, "b", run_id=2)]
    result = TypingAnalyzer(events).analyze()
    assert result["analysis"]["thinking_pause_count"] == 1
    assert result["analysis"]["thinking_pause_opportunities"] == 1
    assert result["ghost_typer_settings"]["pause_frequency"] == 1
