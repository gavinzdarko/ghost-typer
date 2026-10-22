from src.models import Settings
from src.planned_text import PlannedText
from src.text_parser import TextParser
from src.typing_planner import TypingPlanner


def test_many_paragraphs_do_not_materialize_the_growing_prefix(monkeypatch):
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0,
        proofread_probability=0, revisit_probability=0), ai_enabled=False)
    source = "A short paragraph.\n\n" * 1000
    copied = 0
    original = PlannedText.__getattribute__
    def counted(self, name):
        nonlocal copied
        value = original(self, name)
        if name == "text":
            copied += len(value)
        return value
    monkeypatch.setattr(PlannedText, "__getattribute__", counted)
    plan = planner.plan(TextParser().parse(source))
    assert PlannedText().apply(plan.actions).text == source
    assert copied <= 5 * len(source)
