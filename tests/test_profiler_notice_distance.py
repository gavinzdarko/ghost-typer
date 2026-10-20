import pytest

from typing_profiler import KeyEvent, TypingAnalyzer


@pytest.mark.parametrize('following_chars', [0, 3])
def test_profiler_notice_distance_excludes_the_wrong_character(following_chars):
    events = [KeyEvent(index * .1, 'a') for index in range(15)]
    events.append(KeyEvent(1.5, 'x'))
    events.extend(KeyEvent(1.6 + index * .1, 'z') for index in range(following_chars))
    delete_start = 2 + following_chars * .1
    events.extend(KeyEvent(delete_start + index * .1, '<BS>', is_backspace=True)
                  for index in range(1 + following_chars))
    events.append(KeyEvent(delete_start + 1, 'a'))
    profile = TypingAnalyzer(events).analyze()
    assert profile['analysis']['correction_delay_median'] == following_chars
    settings = profile['ghost_typer_settings']
    assert settings['correction_delay_chars_min'] == following_chars
    assert settings['correction_delay_chars_max'] == following_chars
