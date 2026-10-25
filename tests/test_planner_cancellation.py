import threading
from unittest.mock import Mock

import pytest

from src.models import Settings, TextSegment
from src.typing_planner import PlanningCancelled, TypingPlanner


def test_cancel_after_draft_prevents_further_paid_requests_and_next_plan_recovers():
    stopped = threading.Event()
    rewriter = Mock(is_enabled=True)
    def draft(text, context):
        stopped.set()
        return 'rough ' + text
    rewriter.generate_first_draft.side_effect = draft
    # Delayed typo corrections can consume the forced rewrite positions.
    # Keep this scenario focused on cancelling immediately after a draft.
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0),
                            ai_rewriter=rewriter, ai_enabled=False)
    planner._pick_rewrite_positions = lambda *_: [(4, 'word'), (12, 'word')]
    with pytest.raises(PlanningCancelled):
        planner.plan([TextSegment('The ordinary source phrase.')], cancelled=stopped.is_set)
    assert rewriter.generate_first_draft.call_count == 1
    planner._pick_rewrite_positions = lambda *_: []
    assert planner.plan([TextSegment('next')]).actions


def test_cancel_during_thought_detection_skips_all_segment_api_work():
    stopped = threading.Event()
    planner = TypingPlanner(ai_enabled=False)
    def boundaries(text):
        stopped.set()
        return []
    planner._human_errors.find_thought_boundaries = boundaries
    planner._human_errors.process_text = Mock()
    with pytest.raises(PlanningCancelled):
        planner.plan([TextSegment('first'), TextSegment('second')], cancelled=stopped.is_set)
    planner._human_errors.process_text.assert_not_called()


def test_already_cancelled_plan_spends_no_requests():
    planner = TypingPlanner(ai_enabled=False)
    planner._human_errors.find_thought_boundaries = Mock()
    with pytest.raises(PlanningCancelled):
        planner.plan([TextSegment('source')], cancelled=lambda: True)
    planner._human_errors.find_thought_boundaries.assert_not_called()


def test_cancel_during_local_preparation_skips_the_first_paid_call(monkeypatch):
    import src.typing_planner as module
    stopped = threading.Event()
    planner = TypingPlanner(ai_enabled=False)
    validate = module.validate_behavioral_content
    def cancelled_validation(*args):
        value = validate(*args)
        stopped.set()
        return value
    monkeypatch.setattr(module, 'validate_behavioral_content', cancelled_validation)
    planner._human_errors.find_thought_boundaries = Mock()
    with pytest.raises(PlanningCancelled):
        planner.plan([TextSegment('source')], cancelled=stopped.is_set)
    planner._human_errors.find_thought_boundaries.assert_not_called()
