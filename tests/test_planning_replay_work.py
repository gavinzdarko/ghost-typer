"""Bound replay work independently of machine speed or timing thresholds."""
from src.models import Settings
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def test_large_paste_does_not_replay_entire_history_per_chunk(monkeypatch):
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, rewrite_base_probability=0,
        rewrite_max_probability=0, proofread_probability=0, revisit_probability=0))
    planner._human_errors.find_thought_boundaries = lambda _: []
    planner.seed(42)
    text = 'This sentence has several words and punctuation. ' * 400
    visited = [0]
    original = PlannedText.apply

    def counted(self, actions):
        visited[0] += len(actions)
        return original(self, actions)

    monkeypatch.setattr(PlannedText, 'apply', counted)
    plan = planner.plan_plain_text(text)
    assert PlannedText().apply(plan.actions).text == text
    assert visited[0] <= 5 * len(plan.actions)


def test_unnoticed_typo_replay_work_is_linear_and_anchor_window_is_bounded(monkeypatch):
    from src.models import TextSegment, TypeText
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, rewrite_base_probability=0,
        rewrite_max_probability=0, proofread_probability=0, revisit_probability=0))
    planner._pick_mistake_positions = lambda text: set(range(0, len(text), 20))
    planner._build_mistake = lambda *_: ([TypeText(text='b')], 1, ('b', 'a'))
    visited = [0]
    maximum_anchors = [0]
    original = PlannedText.apply
    def counted(self, actions):
        visited[0] += len(actions)
        result = original(self, actions)
        maximum_anchors[0] = max(maximum_anchors[0], len(self.typos))
        return result
    monkeypatch.setattr(PlannedText, 'apply', counted)
    plan = planner.plan([TextSegment('a' * 4000)])
    assert visited[0] <= 5 * len(plan.actions)
    assert maximum_anchors[0] <= planner.profile.proofread.max_proofread_distance
