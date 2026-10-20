from threading import Event
from unittest.mock import Mock, patch
import pytest
from src.keystroke_simulator import KeystrokeSimulator, KeystrokeError
from src.models import TypeText, TypingProfile
from src.orchestrator import Orchestrator


def test_failed_character_does_not_advance_progress():
    with patch('src.keystroke_simulator.Controller'):
        sim = KeystrokeSimulator()
    sim._controller.press.side_effect = OSError('permission denied')
    orch = Orchestrator.__new__(Orchestrator)
    orch._cancel_event = Event()
    orch._profile = TypingProfile.defaults()
    orch._chars_typed = 0
    orch.on_progress = Mock()
    engine = Mock()
    engine.should_peek_pause.return_value = False
    engine.delay_for_keystroke.return_value = 0
    with pytest.raises(KeystrokeError, match='Accessibility'):
        orch._execute_type_text(TypeText(text='hello'), engine, sim, '')
    assert not sim.is_active
    assert orch._chars_typed == 0
    engine.on_char_typed.assert_not_called()
    orch.on_progress.assert_not_called()
    sim._controller.press.assert_called_once_with('h')


def test_backend_error_does_not_attempt_rest_of_raw_string():
    with patch('src.keystroke_simulator.Controller'):
        sim = KeystrokeSimulator()
    sim._controller.press.side_effect = OSError('disconnected')
    with pytest.raises(KeystrokeError):
        sim.type_string_raw('hello')
    assert sim._controller.press.call_count == 1
    assert not sim.is_active
