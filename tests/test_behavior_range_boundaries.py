from src.models import Settings, TextSegment, TypeText
from src.typing_planner import TypingPlanner


def test_adjacent_composition_zones_use_the_new_zone_at_shared_boundary():
    p = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0,
        rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    text = "One, two."
    plan = p.plan([TextSegment(text)], behavioral_content={
        "composition_annotations": [
            {"start": 0, "end": 5, "mode": "composition"},
            {"start": 5, "end": len(text), "mode": "copy"},
        ],
    })
    typed = [a for a in plan.actions if isinstance(a, TypeText)]
    assert next(a for a in typed if "two" in a.text).speed_multiplier == p.profile.behaviors.composition_mode.copy_typing_speed_multiplier
    assert p._get_composition_clause_pause("two.", 5) == 0
    assert p._get_composition_multiplier(len(text)) == 1


def test_quote_end_excludes_following_token_and_document_end():
    p = TypingPlanner(ai_enabled=False)
    p._behavioral_content = {"quote_ranges": [{"start": 0, "end": 5}]}
    assert p._get_quote_multiplier(4) == p.profile.behaviors.quote.speed_multiplier
    assert p._get_quote_multiplier(5) is None


def test_adjacent_quote_ranges_select_the_next_quote_type():
    p = TypingPlanner(ai_enabled=False)
    p._behavioral_content = {"quote_ranges": [
        {"start": 0, "end": 5, "type": "direct_quote"},
        {"start": 5, "end": 10, "type": "paraphrase_close"},
    ]}
    assert p._get_quote_multiplier(5) == p.profile.behaviors.quote.paraphrase_speed_multiplier
