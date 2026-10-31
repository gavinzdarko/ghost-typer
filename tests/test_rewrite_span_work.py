from unittest.mock import Mock

import pytest

from src.models import Settings
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


class CountedText(str):
    copied = 0

    def __getitem__(self, key):
        result = super().__getitem__(key)
        if isinstance(key, slice):
            self.copied += len(result)
        return result


def test_offline_plans_do_not_split_runs_for_unavailable_rewrites():
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0,
                                    false_alarm_rate=0, pause_frequency=0), ai_enabled=False)
    planner.seed(42)
    text = 'word ' * 20_000
    plan = planner.plan_plain_text(text)
    assert PlannedText().apply(plan.actions).text == text
    assert len(plan.actions) < 10


def test_rewrite_candidates_copy_only_the_bounded_context_at_budget():
    rewriter = Mock(is_enabled=True)
    planner = TypingPlanner(ai_rewriter=rewriter, ai_enabled=False)
    planner._draft_requests = planner.MAX_DRAFT_REQUESTS_PER_PLAN
    planner.engine.rewrite_word_count = lambda: 1
    text = CountedText('word ' * 20_000)
    for pos in range(0, len(text), 5):
        assert planner._build_rewrite(text, pos) == ([], 0, 0)
    assert text.copied <= len(text) * 20
    rewriter.generate_first_draft.assert_not_called()


@pytest.mark.parametrize('granularity', ['word', 'sentence', 'paragraph'])
def test_oversized_spans_are_skipped_without_sending_a_truncated_draft(granularity):
    rewriter = Mock(is_enabled=True)
    planner = TypingPlanner(ai_rewriter=rewriter, ai_enabled=False)
    assert planner._build_rewrite('x' * 100_000, 0, granularity) == ([], 0, 0)
    rewriter.generate_first_draft.assert_not_called()


def test_cached_drafts_can_still_be_reused_after_request_budget_is_exhausted():
    rewriter = Mock(is_enabled=True)
    planner = TypingPlanner(ai_rewriter=rewriter, ai_enabled=False)
    planner.engine.rewrite_word_count = lambda: 1
    planner.engine.should_cascade = lambda: False
    planner.engine.should_repeat_rewrite = lambda: False
    planner._draft_cache[('word', 'prefix ')] = 'draft'
    planner._draft_requests = planner.MAX_DRAFT_REQUESTS_PER_PLAN
    actions, _, skipped = planner._build_rewrite('prefix word', 7)
    assert skipped == 4
    assert PlannedText().apply(actions).text == 'word'
    rewriter.generate_first_draft.assert_not_called()
