from src.models import AbandonWord, Settings, TextSegment
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    p = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0,
        false_alarm_rate=0, rewrite_base_probability=0, rewrite_max_probability=0,
        pause_frequency=0), ai_enabled=False)
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
import pytest



@pytest.mark.parametrize("inactive", ["disabled", "zero_probability", "exhausted"])
def test_inactive_abandonment_does_not_split_normal_runs(inactive, monkeypatch):
    p = planner()
    cfg = p.profile.behaviors.abandonment
    if inactive == "disabled":
        cfg.enabled = False
    elif inactive == "zero_probability":
        cfg.probability_per_word = 0
    else:
        cfg.max_per_session = 0
    runs = []
    build = p._build_word_speed_actions
    monkeypatch.setattr(p, "_build_word_speed_actions", lambda text: (runs.append(text), build(text))[1])
    text = "We need approximately " * 400
    result = plan(p, text)
    assert runs == [text]
    assert PlannedText().apply(result.actions).text == text


def test_reaching_abandonment_budget_removes_remaining_run_barriers(monkeypatch):
    p = planner()
    p.profile.behaviors.abandonment.max_per_session = 1
    runs = []
    build = p._build_word_speed_actions
    monkeypatch.setattr(p, "_build_word_speed_actions", lambda text: (runs.append(text), build(text))[1])
    text = "approximately " * 400
    result = plan(p, text)
    assert len([a for a in result.actions if isinstance(a, AbandonWord)]) == 1
    assert runs == [text[len("approximately"):]]


def test_word_lookup_does_not_copy_the_remaining_source_suffix():
    class Source(str):
        slices = 0

        def __getitem__(self, key):
            if isinstance(key, slice):
                self.slices += 1
            return super().__getitem__(key)

    p = planner()
    p._behavioral_content = {"word_abandonments": [
        {"word": "approximately", "replacement": "about", "abandon_after_chars": 4}]}
    text = Source("prefix approximately " + "tail " * 1000)
    assert p._check_word_abandonment(text, len("prefix "))["replacement"] == "about"
    assert text.slices == 0


def test_rejected_autocorrects_with_active_abandonments_have_bounded_replay(monkeypatch):
    p = planner()
    p.profile.behaviors.abandonment.max_per_session = 400
    cfg = p.profile.behaviors.autocorrect
    cfg.probability_per_word = 1
    cfg.min_words_back = cfg.max_words_back = 0
    visited = [0]
    apply = PlannedText.apply

    def counted(self, actions):
        visited[0] += len(actions)
        return apply(self, actions)

    monkeypatch.setattr(PlannedText, "apply", counted)
    text = "approximately teh teh " * 400
    data = {"word_abandonments": [
        {"word": "approximately", "replacement": "about", "abandon_after_chars": 4}],
        "autocorrect_fixes": [{"word": "teh", "correct": "the"}]}
    result = p.plan([TextSegment(text)], behavioral_content=data)
    assert PlannedText().apply(result.actions).text == text.replace("approximately", "about")
    assert visited[0] <= 12 * len(result.actions)
    assert p._autocorrect_count == 0
    # A new paste receives a fresh work budget and can fix a unique word.
    result = p.plan([TextSegment("teh next")], behavioral_content=data)
    assert PlannedText().apply(result.actions).text == "the next"
