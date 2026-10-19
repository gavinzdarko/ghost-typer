from unittest.mock import Mock

from src.typing_planner import TypingPlanner


def planner(*drafts):
    rewriter = Mock(is_enabled=True)
    rewriter.generate_first_draft.side_effect = drafts
    return TypingPlanner(ai_rewriter=rewriter, ai_enabled=False), rewriter


def test_same_phrase_under_different_contexts_gets_distinct_drafts():
    target, rewriter = planner("finance draft", "river draft")
    assert target._get_ai_draft("bank account", "finance") == "finance draft"
    assert target._get_ai_draft("bank account", "rivers") == "river draft"
    assert target._get_ai_draft("bank account", "finance") == "finance draft"
    assert rewriter.generate_first_draft.call_count == 2


def test_context_identity_matches_the_provider_bound():
    target, rewriter = planner("rough draft")
    context = "c" * target.MAX_DRAFT_CONTEXT_CHARS
    assert target._get_ai_draft("final text", context + "first") == "rough draft"
    assert target._get_ai_draft("final text", context + "second") == "rough draft"
    rewriter.generate_first_draft.assert_called_once_with("final text", context)


def test_failure_cache_is_contextual_and_distinct_contexts_keep_request_cap():
    target, rewriter = planner(*([None] * TypingPlanner.MAX_DRAFT_REQUESTS_PER_PLAN))
    for context in range(30):
        assert target._get_ai_draft("final text", str(context)) is None
        assert target._get_ai_draft("final text", str(context)) is None
    assert rewriter.generate_first_draft.call_count == target.MAX_DRAFT_REQUESTS_PER_PLAN
    assert target._draft_requests == target.MAX_DRAFT_REQUESTS_PER_PLAN
