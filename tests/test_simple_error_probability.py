"""Simple/table-cell typing must honor its configured per-character error rate."""
from unittest.mock import Mock, call

from src.models import Rewrite, Settings, TextSegment, TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def test_selected_typo_at_run_boundary_is_not_rerolled_or_lost():
    planner = TypingPlanner(Settings(error_rate=.05, fatigue_enabled=False), ai_enabled=False)
    # Select the second and fourth letters. A batching boundary must not add
    # another lottery that silently discards an already selected typo.
    planner._rng.random = Mock(side_effect=[.9, .01, .9, .01] + [.9] * 10)
    planner.engine.generate_typo = Mock(return_value='z')
    plan = planner.plan([TextSegment('abcd')], simple=True)

    assert planner.engine.generate_typo.call_args_list == [call('b'), call('d')]
    assert sum(isinstance(action, Rewrite) for action in plan.actions) == 2
    assert planner._rng.random.call_count == 4
    replay = PlannedText().apply(plan.actions)
    assert replay.valid and replay.text == 'abcd'


def test_seeded_simple_error_frequency_tracks_the_configured_rate():
    planner = TypingPlanner(Settings(error_rate=.05, fatigue_enabled=False), ai_enabled=False)
    planner.seed(42)
    planner.engine.generate_typo = lambda char: 'z'
    source = 'a' * 10_000
    plan = planner.plan([TextSegment(source)], simple=True)

    # Broad enough for sampling variation, and far above the old double-draw
    # suppression (roughly 0.7% instead of the requested 5%).
    errors = sum(isinstance(action, Rewrite) for action in plan.actions)
    assert 400 <= errors <= 600
    assert PlannedText().apply(plan.actions).text == source
    assert all(len(action.text) <= 9 for action in plan.actions if isinstance(action, TypeText))
