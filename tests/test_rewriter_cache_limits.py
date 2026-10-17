import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.ai_planner import AIRewriter


def rewriter():
    result = AIRewriter(enabled=False)
    result._enabled = True
    result._client = Mock()
    return result


def response(text):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def test_single_drafts_reuse_recent_entries_and_evict_least_recently_used():
    result = rewriter()
    result.MAX_CACHE_ENTRIES = 2
    result._client.messages.create.return_value = response("rough draft")
    for text in ("first text", "second text", "first text", "third text"):
        assert result.generate_first_draft(text) == "rough draft"
    assert list(result._cache) == ["first text", "third text"]
    assert result._client.messages.create.call_count == 3


def test_batch_drafts_obey_total_retained_character_budget():
    result = rewriter()
    result.MAX_CACHE_CHARS = 100
    spans = [{"text": str(i) * 20} for i in range(10)]
    result._client.messages.create.return_value = response(json.dumps(["draft " * 4] * 10))
    assert all(result.generate_drafts_batch(spans))
    assert sum(len(k) + len(v) for k, v in result._cache.items()) <= 100
    assert len(result._cache) == 2
    result.clear_cache()
    assert not result._cache


def test_oversized_successful_draft_is_returned_without_retaining_clipboard():
    result = rewriter()
    result.MAX_CACHE_CHARS = 10
    result._client.messages.create.return_value = response("rough draft")
    assert result.generate_first_draft("source text") == "rough draft"
    assert not result._cache
