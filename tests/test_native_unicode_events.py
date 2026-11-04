"""Roundtrip real Quartz events while preventing all keyboard event posting."""
import sys
import threading
from unittest.mock import patch

import pytest

from src.keystroke_simulator import KeystrokeError, KeystrokeSimulator

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='Quartz native events require macOS')


@pytest.mark.parametrize('char', ['😀', '𐐀', '𝄞'])
@pytest.mark.parametrize('raw', [False, True])
def test_supplementary_characters_roundtrip_both_events(char, raw):
    import Quartz
    with patch('src.keystroke_simulator.Controller'), patch.object(Quartz, 'CGEventPost') as post:
        sim = KeystrokeSimulator()
        if raw:
            sim.type_string_raw(char, delay=0)
        else:
            sim.type_char(char)
    assert post.call_count == 2
    for call, event_type in zip(post.call_args_list, (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp)):
        target, event = call.args
        assert target == Quartz.kCGHIDEventTap
        assert Quartz.CGEventGetType(event) == event_type
        assert Quartz.CGEventKeyboardGetUnicodeString(event, 8, None, None) == (2, char)
    sim._controller.press.assert_not_called()
    sim._controller.release.assert_not_called()
    assert sim.is_active


def test_supplementary_key_up_is_attempted_after_partial_post_failure():
    import Quartz
    with patch('src.keystroke_simulator.Controller'), patch.object(
        Quartz, 'CGEventPost', side_effect=[RuntimeError('failed after posting'), None]
    ) as post:
        sim = KeystrokeSimulator()
        with pytest.raises(KeystrokeError):
            sim.type_char('😀')
    assert post.call_count == 2
    assert Quartz.CGEventGetType(post.call_args_list[-1].args[1]) == Quartz.kCGEventKeyUp
    assert not sim.is_active


def test_supplementary_key_up_failure_stops_the_session():
    import Quartz
    with patch('src.keystroke_simulator.Controller'), patch.object(
        Quartz, 'CGEventPost', side_effect=[None, RuntimeError('release failed')]
    ):
        sim = KeystrokeSimulator()
        with pytest.raises(KeystrokeError):
            sim.type_string_raw('😀😀', delay=0)
    assert not sim.is_active


def test_missing_key_up_event_prevents_key_down_posting():
    import Quartz
    create = Quartz.CGEventCreateKeyboardEvent
    with patch('src.keystroke_simulator.Controller'), patch.object(
        Quartz, 'CGEventCreateKeyboardEvent', side_effect=[create(None, 0, True), None]
    ), patch.object(Quartz, 'CGEventPost') as post:
        sim = KeystrokeSimulator()
        with pytest.raises(KeystrokeError):
            sim.type_char('😀')
    post.assert_not_called()
    assert not sim.is_active


def test_stopped_supplementary_typing_never_posts():
    import Quartz
    with patch('src.keystroke_simulator.Controller'), patch.object(Quartz, 'CGEventPost') as post:
        sim = KeystrokeSimulator()
        sim.stop()
        sim.type_char('😀')
    post.assert_not_called()


def test_paused_supplementary_typing_waits_for_resume():
    import Quartz
    waiting = threading.Event()
    with patch('src.keystroke_simulator.Controller'), patch.object(Quartz, 'CGEventPost') as post:
        sim = KeystrokeSimulator()
        sim.pause()
        original_check = sim._check_state

        def check_state():
            waiting.set()
            return original_check()

        sim._check_state = check_state
        worker = threading.Thread(target=sim.type_char, args=('😀',))
        worker.start()
        try:
            assert waiting.wait(1)
            post.assert_not_called()
            sim.resume()
            worker.join(2)
            assert not worker.is_alive()
            assert post.call_count == 2
        finally:
            sim.stop()
            sim.resume()
            worker.join(2)
