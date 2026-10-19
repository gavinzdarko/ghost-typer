import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.human_errors import HumanErrors


def process(text, modified, **rates):
    errors = HumanErrors(enabled=False, **rates)
    errors._enabled = True
    errors._client = Mock()
    errors._client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=json.dumps({
            "modified_text": modified,
            "misspellings": [{"wrong": "teh", "correct": "The", "position": 0}],
        }))])
    return errors.process_text(text)


def test_zero_misspelling_rate_rejects_model_generated_temporary_typos():
    text = "The student does not know, because they are tired."
    assert process(text, text, misspelling_rate=0) == (text, [])


def test_disabled_grammar_rejects_word_changes_but_accepts_punctuation():
    text = "The student does not know, because they are tired."
    assert process(text, text.replace("does not", "dont"), grammar_error_rate=0,
                   misspelling_rate=0) == (text, [])
    modified = text.replace(",", "")
    assert process(text, modified, grammar_error_rate=0,
                   misspelling_rate=0) == (modified, [])


def test_disabled_punctuation_rejects_punctuation_changes_but_accepts_grammar():
    text = "The student does not know, because they are tired."
    assert process(text, text.replace(",", ""), punctuation_error_rate=0,
                   misspelling_rate=0) == (text, [])
    modified = text.replace("does not", "dont")
    assert process(text, modified, punctuation_error_rate=0,
                   misspelling_rate=0) == (modified, [])


def test_disabled_grammar_rejects_word_boundary_changes():
    text = "The student knows a lot about this subject."
    assert process(text, text.replace("a lot", "alot"), grammar_error_rate=0,
                   misspelling_rate=0) == (text, [])


def test_disabled_punctuation_rejects_relocation_of_the_same_comma():
    text = "The student does not know, because they are tired."
    for modified in ("The student, does not know because they are tired.",
                     "The student does not, know because they are tired."):
        assert process(text, modified, punctuation_error_rate=0,
                       misspelling_rate=0) == (text, [])


def test_disabled_grammar_allows_enabled_apostrophe_punctuation_error():
    text = "The student doesn't know, because they are tired."
    modified = text.replace("doesn't", "doesnt")
    assert process(text, modified, grammar_error_rate=0,
                   misspelling_rate=0) == (modified, [])


def test_disabled_punctuation_rejects_ambiguous_moves_across_repeated_words():
    for text, modified in (
        ("This is really, really important for every student.",
         "This is really really, important for every student."),
        ("We should go, go now and finish our work.",
         "We should go go, now and finish our work."),
        ("This is really, really important because every student knows the answer.",
         "This is really really, important bc every student knows the answer."),
        ("This is really, really important for every student.",
         "This is really Really, important for every student."),
        ("We should go, go now and finish our work.",
         "We should go goes, now and finish our work."),
    ):
        assert process(text, modified, punctuation_error_rate=0,
                       misspelling_rate=0) == (text, [])


def test_disabled_punctuation_keeps_underscores_and_allows_word_length_changes():
    assert not HumanErrors._punctuation_preserved('use snake_case here', 'use snakecase here')
    assert HumanErrors._punctuation_preserved('They does not know, yet.', 'They dont know, yet.')
    assert HumanErrors._punctuation_preserved('Hello, there.', 'HELLO, there.')
