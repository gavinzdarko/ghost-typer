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
