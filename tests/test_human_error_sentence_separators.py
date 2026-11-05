import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.human_errors import HumanErrors


@pytest.mark.parametrize('source, addition', [
    ('Stay home during the storm.', 'Stay!'),
    ('Go home before the rain arrives.', 'Go.'),
    ('Is this the right way home?', 'Is?'),
    ('The remainder of this original paragraph stays unchanged.', 'Go.'),
])
@pytest.mark.parametrize('remove', [False, True])
@pytest.mark.parametrize('opening', ['', 'The opening stays unchanged. '])
def test_sentence_additions_and_deletions_do_not_require_separator_spaces(source, addition, remove, opening):
    original, modified = opening + source, opening + addition + source
    if remove:
        original, modified = modified, original
    errors = HumanErrors(enabled=False)
    errors._enabled = True
    errors._client = Mock()
    errors._client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(text=json.dumps({
            'modified_text': modified, 'misspellings': [],
        }))])
    assert errors.process_text(original) == (original, [])


@pytest.mark.parametrize('before, after', [
    ('three', '3.14'), ('three', '12.50'), ('3.14', '3.15'),
    ('three', '٣.١٤'), ('dont', "don't"),
])
def test_sparse_decimal_and_apostrophe_edits_still_pass(before, after):
    source = f'The student wrote {before} in the original homework paragraph.'
    assert HumanErrors._valid_modified_text(source, source.replace(before, after))
