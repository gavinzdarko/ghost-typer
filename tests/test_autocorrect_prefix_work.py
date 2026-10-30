"""Optional annotations must not force growing-prefix copies per chunk."""
import pytest

from src.models import Settings
from src.planned_text import PlannedText
from src.text_parser import TextParser
from src.typing_planner import TypingPlanner


def planner():
    result = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0,
        proofread_probability=0, revisit_probability=0), ai_enabled=False)
    result.seed(42)
    return result


@pytest.mark.parametrize('paragraphs', [100, 200, 400])
@pytest.mark.parametrize('mode', ['no_match', 'disabled', 'exhausted'])
def test_unused_autocorrect_annotations_keep_prefix_work_bounded(monkeypatch, paragraphs, mode):
    subject = planner()
    if mode == 'disabled':
        subject.profile.behaviors.autocorrect.enabled = False
    elif mode == 'exhausted':
        subject.profile.behaviors.autocorrect.max_per_session = 0
    source = 'A short paragraph.\n\n' * paragraphs
    copied = 0
    original = PlannedText.__getattribute__

    def counted(self, name):
        nonlocal copied
        value = original(self, name)
        if name == 'text':
            copied += len(value)
        return value

    monkeypatch.setattr(PlannedText, '__getattribute__', counted)
    plan = subject.plan(TextParser().parse(source), behavioral_content={
        'autocorrect_fixes': [{'word': 'teh', 'correct': 'the'}]})
    assert PlannedText().apply(plan.actions).text == source
    assert copied <= 5 * len(source)


def test_actual_autocorrect_uses_current_prefix_after_prior_paragraphs():
    subject = planner()
    cfg = subject.profile.behaviors.autocorrect
    cfg.probability_per_word = 1
    cfg.min_words_back = cfg.max_words_back = 1
    source = 'Earlier paragraph.\n\n' * 5 + 'teh next sentence.\n\nFinal words.'
    plan = subject.plan(TextParser().parse(source), behavioral_content={
        'autocorrect_fixes': [{'word': 'teh', 'correct': 'the longer'}]})
    replay = PlannedText().apply(plan.actions)
    assert subject._autocorrect_count == 1
    assert replay.valid
    assert replay.text == source.replace('teh', 'the longer')
    assert replay.cursor == len(replay.text)
