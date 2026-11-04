import pytest

from src.models import Settings, TypingProfile
from src.typing_engine import TypingEngine
from typing_profiler import KeyEvent, TypingAnalyzer


def measured_settings(interval=.2, count=1000, speeds=None):
    analyzer = TypingAnalyzer([KeyEvent(i * interval, 'a') for i in range(count)])
    analyzer.analyze()
    # Isolate the exporter from rolling-window quantization. These represent
    # the same measured proportional speed trend at different typing speeds.
    analyzer.rolling_wpms = [100, 100, 100, 80, 80, 80] if speeds is None else speeds
    return analyzer._build_profile()['ghost_typer_settings']


def test_recorded_slowdown_accumulates_across_characters_without_an_early_cap():
    settings = Settings.from_dict(measured_settings())
    assert settings.fatigue_enabled
    settings.burst_typing_enabled = False
    profile = TypingProfile.defaults()
    profile.fatigue.recovery_probability = 0
    engine = TypingEngine(settings, profile)
    for _ in range(40):
        engine.on_char_typed('a')
    assert engine.state.fatigue_level < .02
    for _ in range(960):
        engine.on_char_typed('a')
    # A 20% WPM decrease corresponds to a 25% increase in key delay.
    assert engine.state.fatigue_level == pytest.approx(.25)
    assert 1 / (1 + engine.state.fatigue_level) == pytest.approx(.8)


def test_fatigue_coefficient_depends_on_characters_instead_of_recording_seconds():
    slow = measured_settings(interval=.2)
    fast = measured_settings(interval=.1)
    assert slow['fatigue_rate'] == fast['fatigue_rate']
    assert slow['wpm'] < fast['wpm']


def test_long_recording_keeps_a_small_nonzero_coefficient():
    settings = measured_settings(count=100000)
    assert 0 < settings['fatigue_rate'] < .00001
    assert Settings.from_dict(settings).fatigue_rate == settings['fatigue_rate']


def test_idle_heavy_recording_exports_a_supported_coefficient_without_default_fallback():
    events = [KeyEvent(i / 10, 'a') for i in range(100)]
    events += [KeyEvent(34, 'b'), KeyEvent(35, 'c')]
    settings = TypingAnalyzer(events).analyze()['ghost_typer_settings']
    assert settings['fatigue_enabled']
    assert settings['fatigue_rate'] == 1
    assert Settings.from_dict(settings).fatigue_rate == settings['fatigue_rate']


@pytest.mark.parametrize('speeds', [[100] * 6, [80, 80, 80, 100, 100, 100],
                                    [100, 100, 100, 0, 0, 0]])
def test_stable_improving_and_idle_windows_do_not_export_fatigue(speeds):
    assert not measured_settings(speeds=speeds)['fatigue_enabled']
