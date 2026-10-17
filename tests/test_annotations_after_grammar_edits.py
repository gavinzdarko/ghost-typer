from copy import deepcopy

from src.models import Settings, TextSegment, TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    return TypingPlanner(Settings(error_rate=0, grammar_error_rate=.15, punctuation_error_rate=0,
        false_alarm_rate=0, rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)


def test_shortened_grammar_edit_keeps_quote_and_later_segment_annotations_aligned():
    p = planner()
    first, modified, last = "He does not run. quote next", "He dont run. quote next", "Final words"
    quote_start = first.index("quote")
    last_start = len(first) + 2
    data = {"quote_ranges": [{"start": quote_start, "end": quote_start + 5}],
            "composition_annotations": [{"start": last_start, "end": last_start + len(last), "mode": "copy"}],
            "distraction_points": [{"position": last_start, "quality": "high"}]}
    unchanged = deepcopy(data)
    p._human_errors.find_thought_boundaries = lambda _: [quote_start, last_start]
    p._human_errors.process_text = lambda text: (modified if text == first else text, [])
    result = p.plan([TextSegment(first), TextSegment("\n\n"), TextSegment(last)], behavioral_content=data)
    assert PlannedText().apply(result.actions).text == modified + "\n\n" + last
    typed = [a for a in result.actions if isinstance(a, TypeText)]
    assert next(a for a in typed if "quote" in a.text).speed_multiplier == p.profile.behaviors.quote.speed_multiplier
    assert next(a for a in typed if "next" in a.text).speed_multiplier == 1
    assert next(a for a in typed if "Final" in a.text).speed_multiplier == p.profile.behaviors.composition_mode.copy_typing_speed_multiplier
    assert p._behavioral_content["distraction_points"][0]["position"] == len(modified) + 2
    assert p._thought_boundaries == {modified.index("quote"), len(modified) + 2}
    assert data == unchanged


def test_boundaries_inside_replaced_text_are_discarded_and_expansions_shift_later_points():
    p = planner()
    p._behavioral_content = {"quote_ranges": [{"start": 1, "end": 2}],
                             "distraction_points": [{"position": 4}]}
    p._thought_boundaries = {1, 4}
    p._remap_source_annotations("cat next", "dog next", 0)
    assert p._behavioral_content["quote_ranges"] == []
    p._remap_source_annotations("dog next", "longer next", 0)
    assert p._behavioral_content["distraction_points"] == [{"position": 7}]
    assert p._thought_boundaries == {7}


def test_large_repetitive_changes_skip_expensive_matching(monkeypatch):
    p = planner()
    p._behavioral_content = {"quote_ranges": [{"start": 10, "end": 20}]}
    p._thought_boundaries = {10}
    monkeypatch.setattr("src.typing_planner.SequenceMatcher", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("unbounded matcher")))
    p._remap_source_annotations("ab" * 4000, "cd" * 4000, 0)
    assert p._behavioral_content["quote_ranges"] == []
    assert p._thought_boundaries == set()
