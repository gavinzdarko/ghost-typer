import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.human_errors import HumanErrors


@pytest.mark.parametrize("source", [
    'The literal { character belongs here.',
    'The literal } character belongs here.',
    'A quoted "brace {" and an escaped slash \\ belong here.',
])
def test_json_recovery_respects_braces_inside_paid_response_text(source):
    data = {"modified_text": source, "misspellings": []}
    response = "Here is the result:\n" + json.dumps(data) + "\nDone."
    assert HumanErrors._parse_json(response) == data
    errors = HumanErrors(enabled=False)
    errors._enabled = True
    errors._client = Mock()
    errors._client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=response)])
    assert errors.process_text(source) == (source, [])
    errors._client.messages.create.assert_called_once()


def test_invalid_prose_braces_do_not_hide_a_later_valid_object():
    assert HumanErrors._parse_json('Some {notes} then {"modified_text": "hello"}.') == {"modified_text": "hello"}


def test_malformed_response_fails_without_retries_or_partial_text():
    assert HumanErrors._parse_json('Result: {"modified_text": "unterminated {') is None
