"""Proofreading must not copy the complete document at each sentence."""
import pytest

from src.models import ApplyFormatting, PressKey, Settings, TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def test_sentence_proofreading_reads_only_the_bounded_tail(monkeypatch):
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0,
        proofread_probability=1, revisit_probability=0), ai_enabled=False)
    planner.seed(0)
    planner._pick_mistake_positions = lambda text: {0} if text.startswith('a') else set()
    planner._build_mistake = lambda *_: ([TypeText(text='b')], 1, ('b', 'a'))
    original_text = PlannedText.text.fget
    materialized = []
    def counted_text(self):
        result = original_text(self)
        materialized.append(len(result))
        return result
    monkeypatch.setattr(PlannedText, 'text', property(counted_text))
    proofread = planner._build_proofread
    windows = []
    def counted_proofread(*args, **kwargs):
        windows.append(len(kwargs['known_text']))
        return proofread(*args, **kwargs)
    monkeypatch.setattr(planner, '_build_proofread', counted_proofread)
    source = 'a short sentence. ' * 400
    plan = planner.plan_plain_text(source)
    assert len(windows) == 400
    assert max(windows) <= planner.profile.proofread.max_proofread_distance
    assert materialized == []
    replay = PlannedText().apply(plan.actions)
    assert replay.valid and replay.text == source


@pytest.mark.parametrize('limit,expected', [(0, ''), (1, 'f'), (4, 'cdef'),
                                          (7, ' abcdef'), (100, 'prefix abcdef')])
def test_suffix_crosses_buffer_pieces_without_materializing(limit, expected):
    state = PlannedText('prefix ')
    state.apply([TypeText(text='ab'), TypeText(text='c'), TypeText(text='def')])
    assert state.suffix(limit) == expected
    assert state._text == 'prefix '
    assert state._appends == ['ab', 'c', 'def']


@pytest.mark.parametrize('start,end,replacement', [(7, 8, '!'), (8, 11, 'xyz'),
    (7, 12, ''), (9, 9, 'insert'), (7, 7, 'first')])
def test_buffered_selection_edits_preserve_prefix_tail_and_cursor(start, end, replacement):
    state = PlannedText('prefix ')
    state.apply([TypeText(text='ab'), TypeText(text='c'), TypeText(text='def')])
    state.apply([PressKey(key='left') for _ in range(len(state) - start)])
    state.apply([ApplyFormatting(shortcut=('shift', 'right')) for _ in range(end - start)])
    state.apply([TypeText(text=replacement)] if replacement else [PressKey(key='backspace')])
    assert state._text == 'prefix '
    assert state.valid and state.cursor == start + len(replacement)
    assert state.text == ('prefix abcdef'[:start] + replacement + 'prefix abcdef'[end:])


def test_proofreading_ascii_tail_after_unicode_prefix_uses_absolute_anchors():
    planner = TypingPlanner(Settings(), ai_enabled=False)
    state = PlannedText('🙂' * 100, track_typos=True)
    state.apply([TypeText(text='teh end.', proofread_typo=('teh', 'the', 0))])
    actions = planner._build_proofread(state.typos, len(state),
        known_text=state.suffix(8))
    assert actions
    state.apply(actions)
    assert state.valid and state.text == '🙂' * 100 + 'the end.'
