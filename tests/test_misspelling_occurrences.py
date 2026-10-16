from src.models import Settings, TextSegment, TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner(misspellings):
    p = TypingPlanner(Settings(error_rate=0, false_alarm_rate=0,
                              rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    p._human_errors.process_text = lambda text: (text, misspellings)
    return p


def test_typo_targets_second_occurrence_without_lowercasing_first():
    text = 'The the end.'
    actions = planner([('teh', 'the', 4)]).plan([TextSegment(text)]).actions
    state = PlannedText().apply(actions)
    assert state.valid and state.text == text
    assert next(a for a in actions if isinstance(a, TypeText)).text == 'The '


def test_repeated_words_in_later_chunks_keep_separate_offsets_and_casing():
    text = 'The first sentence. The second sentence. The third sentence.'
    positions = [text.index('The', 1), text.rindex('The')]
    actions = planner([('teh', 'the', pos) for pos in positions]).plan([TextSegment(text)]).actions
    assert PlannedText().apply(actions).text == text
    assert sum(isinstance(a, TypeText) and a.text == 'teh' for a in actions) == 2


def ai_misspellings(text, approximate_position):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.human_errors import HumanErrors

    errors = HumanErrors(enabled=False)
    errors._enabled = True
    errors._client = Mock()
    errors._client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=json.dumps({
            "modified_text": text,
            "misspellings": [{"wrong": "teh", "correct": "the",
                              "position": approximate_position}],
        }))])
    return errors.process_text(text)[1]


def test_inexact_offset_uses_nearest_occurrence_end_to_end():
    text = "The the end."
    misspellings = ai_misspellings(text, 5)
    assert misspellings == [("teh", "the", 4)]
    actions = planner(misspellings).plan([TextSegment(text)]).actions
    assert PlannedText().apply(actions).text == text
    assert next(action for action in actions if isinstance(action, TypeText)).text == "The "


def test_ambiguous_nearby_occurrences_are_not_relocated():
    assert ai_misspellings("The the end.", 2) == []


def test_search_window_edge_does_not_turn_word_suffix_into_a_word():
    from src.human_errors import HumanErrors

    assert HumanErrors._find_word_near("the rest", "he", 31) == -1
