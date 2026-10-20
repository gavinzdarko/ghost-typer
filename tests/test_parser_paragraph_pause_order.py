from unittest.mock import Mock

from src.models import Pause, Settings
from src.planned_text import PlannedText
from src.text_parser import TextParser
from src.typing_planner import TypingPlanner


def test_parser_segments_pause_after_enter_matches_single_segment_route():
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    planner.engine.paragraph_pause_duration = Mock(return_value=7)
    source = 'First paragraph.\n\nSecond paragraph.'
    plan = planner.plan(TextParser().parse(source))
    pauses = [index for index, action in enumerate(plan.actions)
              if isinstance(action, Pause) and action.duration == 7]
    assert len(pauses) == 2
    assert PlannedText().apply(plan.actions[:pauses[0]]).text == 'First paragraph.\n\n'
    assert PlannedText().apply(plan.actions).text == source
