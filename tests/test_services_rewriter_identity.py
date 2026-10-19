from types import SimpleNamespace
from unittest.mock import Mock
import json
from src.ai_planner import AIRewriter


def rewriter(*outputs):
    service = AIRewriter(enabled=False)
    service._enabled = True
    service._client = Mock()
    service._client.messages.create.side_effect = [SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=output)]) for output in outputs]
    return service


def test_identical_batch_spans_spend_tokens_once_and_fill_every_position():
    service = rewriter(json.dumps(["rough draft"]))
    assert service.generate_drafts_batch([{"text": "final text"}] * 30) == ["rough draft"] * 30
    prompt = service._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert prompt.count("Final: final text") == 1
    assert service.generate_first_draft("final text") == "rough draft"
    service._client.messages.create.assert_called_once()


def test_contexts_do_not_share_a_cached_draft():
    service = rewriter("draft one", "draft two")
    assert service.generate_first_draft("bank account", "finance") == "draft one"
    assert service.generate_first_draft("bank account", "rivers") == "draft two"
    assert service.generate_first_draft("bank account", "finance") == "draft one"
    assert service._client.messages.create.call_count == 2


def test_batch_context_identity_matches_single_calls_without_merging_contexts():
    service = rewriter(json.dumps(["draft one", "draft two"]))
    spans = [{"text": "bank account", "context": context} for context in ["finance", "rivers", "finance"]]
    assert service.generate_drafts_batch(spans) == ["draft one", "draft two", "draft one"]
    assert service.generate_first_draft("bank account", "rivers") == "draft two"
    service._client.messages.create.assert_called_once()


def test_context_bytes_count_towards_retention_budget():
    service = rewriter("rough draft")
    service.MAX_CACHE_CHARS = 30
    assert service.generate_first_draft("final text", "c" * 30) == "rough draft"
    assert not service._cache
