import pytest
from src.ai_planner import AIPlanner
from src.models import ApplyFormatting, FormatType, TextSegment


def data(*texts):
    return {"segments": [{"text": text, "actions": [{"type": "type", "text": text}]} for text in texts]}


def test_duplicate_text_keeps_its_own_source_style():
    planner = AIPlanner(enabled=False)
    plan = planner._convert_ai_plan(data("same", "same"), [
        TextSegment("same", {"bold": True}), TextSegment("same", {"italic": True})])
    assert [a.format_type for a in plan.actions if isinstance(a, ApplyFormatting)] == [
        FormatType.BOLD, FormatType.BOLD, FormatType.ITALIC, FormatType.ITALIC]


def test_splitting_a_formatted_source_keeps_styles():
    planner = AIPlanner(enabled=False)
    plan = planner._convert_ai_plan(data("same", " text"), [TextSegment("same text", {"bold": True})])
    assert sum(isinstance(a, ApplyFormatting) for a in plan.actions) == 4


def test_merging_different_source_styles_is_rejected():
    with pytest.raises(ValueError, match="formatting boundary"):
        AIPlanner(enabled=False)._convert_ai_plan(data("same text"), [
            TextSegment("same", {"bold": True}), TextSegment(" text")])


def test_declared_ai_text_cannot_move_styles_onto_different_actions():
    plan_data = data("a", "b")
    plan_data["segments"][0]["actions"][0]["text"] = "ab"
    plan_data["segments"][1]["actions"] = []
    with pytest.raises(ValueError, match="declared text"):
        AIPlanner(enabled=False)._convert_ai_plan(plan_data, [TextSegment("a", {"bold": True}), TextSegment("b")])


@pytest.mark.parametrize("style", [{"heading_level": 1}, {"list_type": "ordered"}, {"alignment": "center"}])
def test_paragraph_styles_use_source_aware_fallback(style):
    with pytest.raises(ValueError, match="Paragraph formatting"):
        AIPlanner(enabled=False)._convert_ai_plan(data("text"), [TextSegment("text", style)])
