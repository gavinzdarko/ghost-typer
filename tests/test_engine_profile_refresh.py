from src.models import Range, Settings, TypingProfile
from src.typing_engine import TypingEngine
from src.typing_planner import TypingPlanner


def test_new_profile_changes_observed_hunt_delay_and_all_knowledge_sets():
    first = TypingProfile.defaults()
    first.keys.hunt_keys = []
    engine = TypingEngine(Settings(wpm_variance=0), first)
    baseline = engine.base_delay_for_char('a')
    second = TypingProfile.defaults()
    second.keys.hunt_keys = ['a']
    second.keystroke.hunt_key_multiplier = Range(2, 2)
    second.keys.fast_digraphs = ['xy']
    second.keys.slow_digraphs = ['ab']
    second.keys.common_words = ['unique']
    second.keys.text_specific_easy_words = ['topic']
    second.keys.common_doubles = ['x']
    engine.profile = second
    assert engine.base_delay_for_char('a') == baseline * 2
    assert engine._fast_digraphs == {'xy'}
    assert engine._slow_digraphs == {'ab'}
    assert engine._common_words == {'unique', 'topic'}
    assert engine._common_doubles == {'x'}
    assert engine._hunt_keys == {'a'}


def test_planner_profile_assignment_updates_its_engine_knowledge():
    planner = TypingPlanner(ai_enabled=False)
    profile = TypingProfile.defaults()
    profile.keys.hunt_keys = ['e']
    planner.profile = profile
    assert planner.engine.profile is profile
    assert planner.engine._hunt_keys == {'e'}
