import pytest

from src.models import Settings, TextSegment, TypingProfile
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


@pytest.mark.parametrize('replacement', ['the', 'the longer', 'a'])
def test_false_alarm_does_not_undo_or_corrupt_an_immediate_autocorrect(replacement):
    profile = TypingProfile.from_dict({
        'mistakes': {'false_alarm_weights': [0, 1]},
        'behaviors': {'autocorrect': {'probability_per_word': 1, 'min_words_back': 0,
                                     'max_words_back': 0}},
    })
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=1, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0,
        proofread_probability=0, revisit_probability=0), profile=profile, ai_enabled=False)
    planner.seed(42)
    plan = planner.plan([TextSegment('hello teh')], behavioral_content={
        'autocorrect_fixes': [{'word': 'teh', 'correct': replacement}]})
    replay = PlannedText().apply(plan.actions)
    assert any(action.description.startswith('False alarm:') for action in plan.actions)
    assert planner._autocorrect_count == 1
    assert replay.valid and replay.text == 'hello ' + replacement
    assert replay.cursor == len(replay)
