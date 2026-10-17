from src.models import AbandonWord, Settings, TextSegment
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    p = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0,
        false_alarm_rate=0, rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    p.profile.behaviors.abandonment.probability_per_word = 1
    return p


def plan(p, text):
    return p.plan([TextSegment(text)], behavioral_content={"word_abandonments": [
        {"word": "approximately", "replacement": "about", "abandon_after_chars": 4}]})


def test_candidate_in_middle_of_normal_run_is_reached():
    p = planner()
    result = plan(p, "We need approximately three miles.")
    assert PlannedText().apply(result.actions).text == "We need about three miles."
    assert len([a for a in result.actions if isinstance(a, AbandonWord)]) == 1
    assert p._char_position == len("We need approximately three miles.")


def test_each_whole_word_candidate_is_considered_without_matching_suffixes():
    p = planner()
    p.profile.behaviors.abandonment.max_per_session = 2
    result = plan(p, "preapproximately approximately and approximately approximately")
    assert PlannedText().apply(result.actions).text == "preapproximately about and about approximately"
    p._behavioral_content = {"word_abandonments": [
        {"word": "approximately", "replacement": "about", "abandon_after_chars": 4}]}
    assert p._check_word_abandonment("preapproximately", 3) is None


def test_disabled_abandonment_consumes_all_candidates_normally():
    p = planner()
    p.profile.behaviors.abandonment.enabled = False
    text = "We need approximately approximately now."
    assert PlannedText().apply(plan(p, text).actions).text == text
