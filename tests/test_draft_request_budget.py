from unittest.mock import Mock
import pytest

from src.models import Settings
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    p = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0, false_alarm_rate=0, rewrite_max_probability=0, rewrite_base_probability=0))
    p._ai_rewriter = Mock(is_enabled=True)
    p._ai_rewriter.generate_first_draft.side_effect = lambda text, context: 'rough ' + text
    p._human_errors.find_thought_boundaries = lambda text: []
    return p


def test_no_speculative_draft_requests_when_no_rewrites_selected():
    p = planner()
    text = 'A document with no selected rewrites. ' * 30
    plan = p.plan_plain_text(text)
    p._ai_rewriter.generate_drafts_batch.assert_not_called()
    p._ai_rewriter.generate_first_draft.assert_not_called()
    assert PlannedText().apply(plan.actions).text == text


def test_hard_limit_includes_failed_and_repeated_requests_and_caches_results():
    p = planner()
    assert p._get_ai_draft('first') == 'rough first'
    assert p._get_ai_draft('first') == 'rough first'
    assert p._ai_rewriter.generate_first_draft.call_count == 1
    p._ai_rewriter.generate_first_draft.side_effect = None
    p._ai_rewriter.generate_first_draft.return_value = None
    assert p._get_ai_draft('failed') is None
    assert p._get_ai_draft('failed') is None
    for idx in range(50):
        assert p._get_ai_draft('unique ' + str(idx)) is None
    assert p._ai_rewriter.generate_first_draft.call_count == p.MAX_DRAFT_REQUESTS_PER_PLAN


def test_nested_and_repeated_rewrites_fall_back_locally_at_budget():
    p = planner()
    p._pick_rewrite_positions = lambda text, *_: [(m.start(), 'word') for m in __import__('re').finditer(r'\b\w+', text)]
    p.engine.should_cascade = lambda: True
    p.engine.should_repeat_rewrite = lambda: True
    text = ' '.join('word' + str(i) for i in range(80))
    plan = p.plan_plain_text(text)
    state = PlannedText().apply(plan.actions)
    assert state.valid and state.text == text
    assert p._ai_rewriter.generate_first_draft.call_count == p.MAX_DRAFT_REQUESTS_PER_PLAN
    # A fresh planning session gets a fresh bounded budget and releases old text.
    p._pick_rewrite_positions = lambda *_: []
    p.plan_plain_text('new session')
    assert p._draft_requests == 0 and p._draft_cache == {}


def test_rejected_revisit_proposals_are_bounded_and_non_ascii_spends_nothing():
    p = planner()
    p.settings.revisit_probability = 10
    p._ai_rewriter.pick_revisit_targets.return_value = [{'original': 'missing', 'revised': 'unused'}]
    for _ in range(40):
        assert p._maybe_build_revisit('ASCII paragraph with no requested target. ' * 20, 3000) == []
    assert p._ai_rewriter.pick_revisit_targets.call_count == p.MAX_REVISIT_REQUESTS_PER_PLAN
    p.plan_plain_text('fresh plan')
    assert p._revisit_requests == 0
    p._ai_rewriter.pick_revisit_targets.reset_mock()
    for _ in range(40):
        assert p._maybe_build_revisit('café paragraph ' * 30, 3000) == []
    p._ai_rewriter.pick_revisit_targets.assert_not_called()


@pytest.mark.parametrize('draft', ['draft\tother field', 'draft\nnew paragraph',
                                  'draft\x08control', 'cafe\u0301 draft', '👪 draft'])
def test_unsafe_temporary_draft_is_cached_as_failure_and_original_is_preserved(draft):
    p = planner()
    p._ai_rewriter.generate_first_draft.side_effect = None
    p._ai_rewriter.generate_first_draft.return_value = draft
    p.engine.rewrite_word_count = lambda: 1
    text = 'An ordinary source phrase.'
    p._pick_rewrite_positions = lambda *_: [(3, 'word')]
    plan = p.plan_plain_text(text)
    assert PlannedText().apply(plan.actions).text == text
    assert p._get_ai_draft('ordinary') is None
    assert p._ai_rewriter.generate_first_draft.call_count == 1


def test_unicode_source_bypasses_temporary_and_repeated_rewrites():
    p = planner()
    p.engine.should_repeat_rewrite = lambda: True
    p._pick_rewrite_positions = lambda *_: [(0, 'sentence')]
    text = 'A cafe\u0301 for the family 👪.'
    plan = p.plan_plain_text(text)
    assert PlannedText().apply(plan.actions).text == text
    p._ai_rewriter.generate_first_draft.assert_not_called()
