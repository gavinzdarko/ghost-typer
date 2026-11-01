from unittest.mock import Mock

import pytest

from src.models import MakeMistake, Rewrite, Settings, TextSegment, TypeText
from src.planned_text import PlannedText
from src.typing_planner import PlanningCancelled, TypingPlanner


def planner(**settings):
    values = dict(error_rate=.05, grammar_error_rate=0, punctuation_error_rate=0,
                  false_alarm_rate=0, proofread_probability=0,
                  rewrite_base_probability=0, rewrite_max_probability=0,
                  pause_frequency=0, fatigue_rate=.001)
    values.update(settings)
    target = TypingPlanner(Settings(**values), ai_enabled=False)
    target.profile.fatigue.max_level = 1
    target.profile.mistakes.fatigue_error_boost = .8
    target.profile.mistakes.unnoticed_rate = 0
    # Keep correction distance fixed so source positions can be compared.
    target.engine.generate_typo = lambda char: 'z' if char != 'z' else 'x'
    target.engine.is_fast_loop_correction = lambda: False
    target.engine.chars_before_noticing_mistake = lambda: 0
    target.seed(37)
    return target


def typo_positions(plan):
    position = 0
    result = []
    for action in plan.actions:
        if isinstance(action, MakeMistake):
            result.append(position)
            position += len(action.correct_text)
        elif isinstance(action, TypeText):
            position += len(action.text)
    return result


def test_fatigue_increases_errors_later_in_a_real_plan_and_off_keeps_base_rate():
    text = 'ordinary typing words ' * 100
    tired = planner().plan([TextSegment(text)])
    fresh = planner(fatigue_enabled=False).plan([TextSegment(text)])
    tired_positions, fresh_positions = typo_positions(tired), typo_positions(fresh)
    assert len(tired_positions) > 4 * len(fresh_positions)
    early = sum(position < 500 for position in tired_positions)
    late = sum(position >= len(text) - 500 for position in tired_positions)
    assert late > 2 * early
    for plan in (tired, fresh):
        replay = PlannedText().apply(plan.actions)
        assert replay.valid and replay.text == text


@pytest.mark.parametrize('simple', [False, True])
def test_zero_errors_override_fatigue_in_both_planning_modes(simple):
    target = planner(error_rate=0, fatigue_rate=1)
    target.profile.mistakes.fatigue_error_boost = 1
    text = ('ordinary words ' * 100) + 'cafe\u0301\tend'
    plan = target.plan([TextSegment(text)], simple=simple)
    assert not any(isinstance(action, (MakeMistake, Rewrite)) for action in plan.actions)
    replay = PlannedText().apply(plan.actions)
    assert replay.valid and replay.text == text


@pytest.mark.parametrize('simple', [False, True])
def test_zero_fatigue_rate_matches_disabled_fatigue_exactly(simple):
    text = 'ordinary words with punctuation. ' * 20
    disabled = planner(fatigue_enabled=False, fatigue_rate=0)
    enabled = planner(fatigue_enabled=True, fatigue_rate=0)
    assert enabled.plan([TextSegment(text)], simple=simple).actions == disabled.plan(
        [TextSegment(text)], simple=simple).actions


@pytest.mark.parametrize('simple', [False, True])
def test_simple_and_regular_plans_clamp_saturated_error_rate_and_reset(simple):
    target = planner(error_rate=.1, fatigue_rate=1)
    target.profile.mistakes.fatigue_error_boost = 1
    target._rng.random = Mock(return_value=.5)
    segments = [TextSegment('a' * 50)]
    first = target.plan(segments, simple=simple)
    second = target.plan(segments, simple=simple)
    # The first character starts fresh; all later characters exceed the draw.
    if simple:
        assert sum(isinstance(action, Rewrite) for action in first.actions) == 49
        assert sum(isinstance(action, Rewrite) for action in second.actions) == 49
    else:
        assert typo_positions(first) == typo_positions(second) == list(range(1, 50))
    assert target._planned_error_rate(0) == 1
    for plan in (first, second):
        replay = PlannedText().apply(plan.actions)
        assert replay.valid and replay.text == 'a' * 50


def test_progress_counts_structural_breaks_and_unicode_without_unsafe_corrections():
    target = planner(error_rate=.1, fatigue_rate=.01)
    target.profile.mistakes.fatigue_error_boost = 1
    target._rng.random = Mock(return_value=.5)
    segments = [TextSegment('é' * 20), TextSegment('\n' * 30), TextSegment('abc')]
    plan = target.plan(segments)
    assert len(typo_positions(plan)) == 3
    for action in plan.actions:
        if isinstance(action, MakeMistake):
            assert action.wrong_text.isascii() and action.correct_text.isascii()
    replay = PlannedText().apply(plan.actions)
    assert replay.valid and replay.text == ''.join(segment.text for segment in segments)


def test_rewritten_source_advances_fatigue_without_counting_temporary_draft_length():
    target = planner(error_rate=.1, fatigue_rate=.01)
    target.profile.mistakes.fatigue_error_boost = 1
    target._rng.random = Mock(return_value=.5)
    target._ai_rewriter = Mock(is_enabled=True)
    target._ai_rewriter.generate_first_draft.return_value = 'rough'
    target._pick_rewrite_positions = lambda text, *_: [(0, 'word')] if len(text) > 3 else []
    target.engine.should_cascade = lambda: False
    target.engine.should_repeat_rewrite = lambda: False
    segments = [TextSegment('ordinary' * 10), TextSegment('abc')]
    plan = target.plan(segments)
    assert len(typo_positions(plan)) == 3
    replay = PlannedText().apply(plan.actions)
    assert replay.valid and replay.text == ''.join(segment.text for segment in segments)


def test_long_typo_scan_observes_cancellation_before_finishing():
    target = planner()
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks == 3

    target._cancelled = cancelled
    target._rng.random = Mock(return_value=.99)
    with pytest.raises(PlanningCancelled):
        target._pick_mistake_positions('a' * 10000)
    assert target._rng.random.call_count <= 512
