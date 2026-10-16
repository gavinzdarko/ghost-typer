import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.human_errors import HumanErrors


def process(text, data, stop_reason='end_turn'):
    errors = HumanErrors(enabled=False)
    errors._enabled = True
    errors._client = Mock()
    errors._client.messages.create.return_value = SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(text=json.dumps(data))])
    return errors.process_text(text)


@pytest.mark.parametrize('modified', [None, 12, '', 'unrelated replacement', 'First paragraph.'])
def test_invalid_ai_replacements_never_discard_clipboard_text(modified):
    text = 'First paragraph.\n\nSecond paragraph with details.'
    assert process(text, {'modified_text': modified}) == (text, [])


def test_truncated_response_and_nonobject_json_keep_original():
    text = 'This is the complete input text.'
    assert process(text, {'modified_text': text}, 'max_tokens') == (text, [])
    assert process(text, [text]) == (text, [])


def test_sparse_edits_survive_and_invalid_misspelling_records_are_ignored():
    text = 'The student does not know because they are tired.\n\nNext paragraph.'
    modified = text.replace('does not', 'dont')
    result = process(text, {'modified_text': modified, 'misspellings': [None, {'position': 'bad'},
                           {'wrong': 'teh', 'correct': 'the', 'position': 0}]})
    assert result == (modified, [('teh', 'The', 0)])
