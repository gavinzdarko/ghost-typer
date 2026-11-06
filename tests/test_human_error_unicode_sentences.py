"""AI error generation must preserve sentences across writing systems."""
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


@pytest.mark.parametrize('addition', ['Go。', 'Go！', 'Go？', 'Go…', 'Go．', 'Go｡',
                                       '走。', 'Go؟', 'Go۔', 'Go।', 'Go‼', 'Go\U00011047'])
@pytest.mark.parametrize('remove', [False, True])
@pytest.mark.parametrize('opening', ['', 'The opening remains unchanged. '])
def test_unicode_sentence_additions_and_deletions_preserve_original(addition, remove, opening):
    # Matching shares "Go" and can leave only the terminator plus the next
    # word as the edit. Exercise that case with and without preceding text.
    source = opening + 'Go home before the rain arrives. The remaining details stay unchanged.'
    modified = opening + addition + source[len(opening):]
    if remove:
        source, modified = modified, source
    assert process(source, modified) == (source, [])


@pytest.mark.parametrize('before, after', [
    ('wait.', 'wait…'), ('wait', 'wait。'), ('wait。', 'wait'),
    ('three', '3.14'), ('three', '٣.١٤'), ('three', '３．１４'),
    ('dont', "don't"), ('after school', 'after school,'),
])
def test_sparse_unicode_punctuation_decimal_and_apostrophe_edits_still_pass(before, after):
    source = f'The student wrote {before} in the original homework paragraph.'
    modified = source.replace(before, after)
    assert process(source, modified) == (modified, [])
