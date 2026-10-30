import pytest

from src.models import Settings
from typing_profiler import KeyEvent, TypingAnalyzer


def analyze(times, chars):
    events = [KeyEvent(timestamp, char, is_space=char == ' ', is_enter=char == '\n')
              for timestamp, char in zip(times, chars)]
    analyzer = TypingAnalyzer(events)
    profile = analyzer.analyze()
    exported = profile['ghost_typer_settings']
    loaded = Settings.from_dict(exported).to_dict()
    assert {key: loaded[key] for key in exported} == exported
    return profile, analyzer


def test_sparse_recording_exports_minimum_supported_speed_with_raw_measurement():
    profile, _ = analyze([index * 40 for index in range(20)], 'a' * 20)
    assert profile['ghost_typer_settings']['wpm'] == 1
    assert profile['analysis']['avg_wpm'] == .3


def test_fast_input_exports_maximum_supported_speed_with_raw_measurement():
    profile, _ = analyze([index * .005 for index in range(20)], 'a' * 20)
    assert profile['ghost_typer_settings']['wpm'] == 1000
    assert profile['analysis']['avg_wpm'] > 2500


@pytest.mark.parametrize('boundary,setting', [('a', 'pause_duration'),
                                               (' ', 'sentence_pause'),
                                               ('\n', 'paragraph_pause')])
def test_idle_gap_keeps_raw_pause_but_exports_supported_durations(boundary, setting):
    before = 'abcdefgh.' + boundary
    chars = before + 'klmnopqrst'
    times = [index * .1 for index in range(10)] + [7200 + index * .1 for index in range(10)]
    profile, analyzer = analyze(times, chars)
    settings = profile['ghost_typer_settings']
    assert settings[setting + '_min'] == settings[setting + '_max'] == 3600
    assert analyzer.pauses[0].duration > 7199
    assert profile['analysis']['session_duration_sec'] > 7200
