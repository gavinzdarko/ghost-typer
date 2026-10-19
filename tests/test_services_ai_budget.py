from types import SimpleNamespace
from unittest.mock import Mock
import json

from src.ai_planner import AIPlanner, AIProfileGenerator, AIRewriter
from src.models import TextSegment


def enable(service, text="[]"):
    service._enabled = True
    service._client = Mock()
    service._client.messages.create.return_value = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(text=text)])
    return service


def test_large_and_empty_full_plans_do_not_call_paid_api():
    planner = enable(AIPlanner(enabled=False))
    planner._fallback_planner = Mock()
    for text in ("", "x" * (planner.MAX_INPUT_CHARS + 1)):
        planner.plan([TextSegment(text)])
    planner._client.messages.create.assert_not_called()
    assert planner._fallback_planner.plan.call_count == 2


def test_full_plan_response_budget_scales_with_input():
    planner = enable(AIPlanner(enabled=False), json.dumps({"segments": [
        {"text": "abc", "actions": [{"type": "type", "text": "abc"}]}]}))
    planner.plan([TextSegment("abc")])
    assert planner._client.messages.create.call_args.kwargs["max_tokens"] == 512


def test_batch_bounds_prompt_and_keeps_all_result_positions():
    rewriter = enable(AIRewriter(enabled=False))
    spans = [{"text": "word " * 100, "context": "c" * 5000} for _ in range(100)]
    results = rewriter.generate_drafts_batch(spans)
    assert len(results) == len(spans)
    prompt = rewriter._client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert len(prompt) < rewriter.MAX_BATCH_CHARS + 1000
    assert "c" * (rewriter.MAX_CONTEXT_CHARS + 1) not in prompt


def test_invalid_drafts_and_empty_profiles_do_not_spend_tokens():
    rewriter = enable(AIRewriter(enabled=False))
    assert rewriter.generate_first_draft("") is None
    assert rewriter.generate_first_draft("x" * (rewriter.MAX_SPAN_CHARS + 1)) is None
    assert rewriter.generate_drafts_batch([{"text": ""}]) == [None]
    assert rewriter.pick_revisit_targets("long enough " * 30, 0) == []
    rewriter._client.messages.create.assert_not_called()
    generator = enable(AIProfileGenerator(enabled=False))
    generator.generate_profile("  ")
    assert generator.generate_behavioral_content("") == {}
    generator._client.messages.create.assert_not_called()


def test_truncated_single_draft_is_never_used_or_cached():
    rewriter = enable(AIRewriter(enabled=False), "rough draft")
    rewriter._client.messages.create.return_value.stop_reason = "max_tokens"
    assert rewriter.generate_first_draft("final text") is None
    assert not rewriter._cache


def test_all_full_plan_fallbacks_are_local_including_after_settings_update():
    from unittest.mock import patch
    from src.models import Settings
    client = Mock()
    client.messages.create.side_effect = RuntimeError("API unavailable")
    with patch("anthropic.Anthropic", return_value=client) as factory:
        planner = AIPlanner(api_key="test")
        assert not planner._fallback_planner._human_errors.is_enabled
        assert planner._fallback_planner._ai_rewriter is None
        planner.plan([TextSegment("A short source sentence.")])
        assert client.messages.create.call_count == 1
        planner.plan([TextSegment("x" * (planner.MAX_INPUT_CHARS + 1))])
        assert client.messages.create.call_count == 1
        planner.update_settings(Settings())
        assert not planner._fallback_planner._human_errors.is_enabled
        factory.assert_called_once_with(api_key="test", max_retries=0)
