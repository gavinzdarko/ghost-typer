import threading
from unittest.mock import Mock, patch

from orchestrator_support import Orchestrator
from src.models import TypingProfile


def app():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}):
        result = Orchestrator()
    result.ai_profile_generator = Mock(is_enabled=True)
    return result


def test_cancellation_does_not_wait_for_api_and_prevents_call_pileup():
    obj = app()
    release = threading.Event()
    started = threading.Event()
    def blocked(text):
        started.set()
        release.wait(2)
        return TypingProfile.defaults()
    obj.ai_profile_generator.generate_profile.side_effect = blocked
    obj.ai_profile_generator.generate_behavioral_content.side_effect = blocked
    thread = threading.Thread(target=obj._generate_session_behaviors, args=('hello',))
    try:
        thread.start()
        assert started.wait(1)
        obj._cancel_event.set()
        thread.join(1)
        assert not thread.is_alive()
        obj._cancel_event.clear()
        obj._generate_session_behaviors('next paste')
        assert obj.ai_profile_generator.generate_profile.call_count == 1
    finally:
        release.set()
        thread.join(2)
        obj._profile_executor.shutdown(wait=True)


def test_one_failed_profile_does_not_abort_behavior_or_typing():
    obj = app()
    obj.ai_profile_generator.generate_profile.side_effect = RuntimeError('API unavailable')
    obj.ai_profile_generator.generate_behavioral_content.return_value = {'word_speeds': []}
    try:
        profile, behavior = obj._generate_session_behaviors('hello')
        assert isinstance(profile, TypingProfile)
        assert behavior == {'word_speeds': []}
    finally:
        obj._profile_executor.shutdown(wait=True)
