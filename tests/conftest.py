"""Keep routine verification independent of personal API credentials and billing."""
import anthropic
import pytest


@pytest.fixture(autouse=True)
def isolate_anthropic_requests(monkeypatch):
    # An explicit empty value also prevents a later load_dotenv() from restoring
    # a personal key. Individual credential tests can still override it.
    monkeypatch.setenv('ANTHROPIC_API_KEY', '')

    def blocked_request(*args, **kwargs):
        raise AssertionError('Real Anthropic requests are disabled in tests; mock the client')

    # Even tests that supply a key must mock responses before reaching the SDK
    # transport. Patch below messages.create so existing client mocks still work.
    monkeypatch.setattr(anthropic.Anthropic, 'request', blocked_request)
