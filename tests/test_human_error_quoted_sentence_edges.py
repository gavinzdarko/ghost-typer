"""Shared closing delimiters must not conceal AI-added/deleted sentences."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.human_errors import HumanErrors


def process(source, modified):
    errors = HumanErrors(enabled=False)
    errors._enabled = True
    errors._client = Mock()
    errors._client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(text=json.dumps({
            'modified_text': modified, 'misspellings': [],
        }))])
    return errors.process_text(source)


@pytest.mark.parametrize('word', ['"Run"', "'Run'", '“Run”', '«Run»', '(Run)',
                                   '[Run]', '「Run」', '《Run》', '`Run`',
                                   '＂Run＂', '＇Run＇', '｀Run｀', '„Run“', '⹂Run⹂',
                                   '"Run\u0301"', '“क्यों”', 'cafe\u0301', 'नहीं',
                                   'का', 'a\u20dd'])
@pytest.mark.parametrize('separator', ['', ' '])
@pytest.mark.parametrize('remove', [False, True])
@pytest.mark.parametrize('opening', ['', 'The opening remains unchanged. '])
def test_shared_quoted_and_bracketed_prefix_cannot_hide_a_sentence(word, separator, remove, opening):
    source = opening + f'{word}{separator} means move fast. The remaining instructions stay exactly as written.'
    modified = opening + f'{word}{separator}. ' + source[len(opening):]
    if remove:
        source, modified = modified, source
    assert process(source, modified) == (source, [])


@pytest.mark.parametrize('before, after', [
    ('"Run" means', '"Run". means'), ('(Run) means', '(Run). means'),
    ('"Run" means', '"Run" means,'), ('dont', "don't"), ('three', '3.14'),
])
def test_punctuation_only_quoted_edits_and_local_grammar_remain_allowed(before, after):
    source = f'The student wrote {before} in the original homework paragraph.'
    modified = source.replace(before, after)
    assert process(source, modified) == (modified, [])
