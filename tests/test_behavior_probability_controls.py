import pytest

from src.models import AbandonWord, Rewrite, Settings, TextSegment
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    p = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0,
        false_alarm_rate=0, rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    p.profile.behaviors.autocorrect.min_words_back = p.profile.behaviors.autocorrect.max_words_back = 0
    return p


@pytest.mark.parametrize("probability", [0, 1])
def test_abandonment_probability_controls_selected_candidate(probability):
    p = planner()
    p.profile.behaviors.abandonment.probability_per_word = probability
    plan = p.plan([TextSegment("approximately now")], behavioral_content={"word_abandonments": [
        {"word": "approximately", "replacement": "about", "abandon_after_chars": 4}]})
    assert any(isinstance(a, AbandonWord) for a in plan.actions) == bool(probability)


@pytest.mark.parametrize("probability", [0, 1])
def test_restructuring_probability_controls_temporary_draft(probability):
    p = planner()
    p.profile.behaviors.restructuring.probability_per_sentence = probability
    text = "This is a final sentence."
    plan = p.plan([TextSegment(text)], behavioral_content={"sentence_restructures": [
        {"original_sentence": text, "first_draft": "This is an awkward first draft."}]})
    assert any(isinstance(a, Rewrite) for a in plan.actions) == bool(probability)
    assert PlannedText().apply(plan.actions).text == text


@pytest.mark.parametrize("probability", [0, 1])
def test_autocorrect_probability_controls_deferred_edit(probability):
    p = planner()
    p.profile.behaviors.autocorrect.probability_per_word = probability
    plan = p.plan([TextSegment("teh next words")], behavioral_content={"autocorrect_fixes": [
        {"word": "teh", "correct": "the"}]})
    assert PlannedText().apply(plan.actions).text == ("the next words" if probability else "teh next words")
