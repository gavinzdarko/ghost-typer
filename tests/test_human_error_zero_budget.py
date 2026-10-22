"""Disabled error generation should spend neither API calls nor plan budget."""
from unittest.mock import Mock

import pytest

from src.human_errors import HumanErrors


def test_all_zero_rates_skip_paid_request_and_preserve_budget():
    errors = HumanErrors(enabled=False, misspelling_rate=0,
                         grammar_error_rate=0, punctuation_error_rate=0)
    errors._enabled = True
    errors._client = Mock()
    assert errors.process_text('Source text stays exactly the same.') == (
        'Source text stays exactly the same.', [])
    errors._client.messages.create.assert_not_called()
    assert errors._requests == 0


@pytest.mark.parametrize('rate', ['misspelling_rate', 'grammar_error_rate', 'punctuation_error_rate'])
def test_each_independent_enabled_rate_can_still_generate_errors(rate):
    rates = dict(misspelling_rate=0, grammar_error_rate=0, punctuation_error_rate=0)
    rates[rate] = .1
    errors = HumanErrors(enabled=False, **rates)
    errors._enabled = True
    errors._client = Mock()
    errors._ai_process_text = Mock(return_value=('source', []))
    assert errors.process_text('source') == ('source', [])
    errors._ai_process_text.assert_called_once_with('source')
    assert errors._requests == 1
