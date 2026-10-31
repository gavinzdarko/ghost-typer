import anthropic
import pytest

from src.human_errors import HumanErrors


def test_default_services_do_not_enable_paid_calls_from_personal_credentials():
    assert not HumanErrors().is_enabled


def test_explicit_test_credentials_cannot_reach_the_paid_transport():
    client = anthropic.Anthropic(api_key='fake-test-key', max_retries=0)
    try:
        with pytest.raises(AssertionError, match='Real Anthropic requests are disabled'):
            client.messages.create(model='unused', max_tokens=1,
                                   messages=[{'role': 'user', 'content': 'not sent'}])
    finally:
        client.close()
