from unittest.mock import Mock

from src.models import Settings, TextSegment, TypeText
from src.typing_planner import TypingPlanner, _Chunk


def planner():
    return TypingPlanner(Settings(error_rate=0, grammar_error_rate=0, punctuation_error_rate=0, false_alarm_rate=0, rewrite_max_probability=0, rewrite_base_probability=0))


def test_every_token_uses_its_own_source_offset():
    p = planner()
    p._char_position = 20
    p._behavioral_content = {'quote_ranges': [{'start': 26, 'end': 30}]}
    p._get_quote_multiplier = Mock(return_value=None)
    p._get_composition_multiplier = Mock(return_value=1)
    p._get_composition_clause_pause = Mock(return_value=0)
    p._build_word_speed_actions('first  second, third')
    assert [c.args[0] for c in p._get_quote_multiplier.call_args_list] == [20, 27, 35]
    assert [c.args[0] for c in p._get_composition_multiplier.call_args_list] == [20, 27, 35]
    assert [c.args[1] for c in p._get_composition_clause_pause.call_args_list] == [20, 27, 35]
    assert p._char_position == 20  # caller consumes this source run once


def test_quote_range_does_not_affect_whole_run():
    p = planner()
    p._behavioral_content = {'quote_ranges': [{'start': 4, 'end': 8}]}
    actions = p._build_word_speed_actions('one quote end')
    speeds = [a.speed_multiplier for a in actions if isinstance(a, TypeText) and 'quote' in a.text]
    assert speeds == [p.profile.behaviors.quote.speed_multiplier]
    assert any(isinstance(a, TypeText) and a.text.startswith('one') and a.speed_multiplier == 1 for a in actions)


def test_all_special_branches_advance_consumed_source_positions():
    p = planner()
    p.profile.misspelling.notice_after_space_probability = 1
    p._plan_chunk(_Chunk('receive next'), {'receive': ('recieve', 'receive')})
    assert p._char_position == len('receive next')
    p._plan_chunk(_Chunk('\n\n'))
    assert p._char_position == len('receive next\n\n')
    p = planner()
    p._pick_mistake_positions = lambda text: {0}
    p._build_mistake = lambda *_: ([TypeText(text='ab')], 2, None)
    p._plan_chunk(_Chunk('abc'))
    assert p._char_position == 3
    p = planner()
    p._pick_rewrite_positions = lambda *_: [(0, 'word')]
    p._build_rewrite = lambda *_args, **_kwargs: ([TypeText(text='ab')], 2, 2)
    p._plan_chunk(_Chunk('abc'))
    assert p._char_position == 3
    p = planner()
    p._behavioral_content = {'word_abandonments': [{'word': 'hello', 'replacement': 'greetings', 'abandon_after_chars': 2}]}
    p._plan_chunk(_Chunk('hello world'))
    assert p._char_position == len('hello world')


def test_thought_boundaries_include_prior_segments_and_breaks():
    p = planner()
    p._human_errors.find_thought_boundaries = lambda _: [7]
    plan = p.plan([TextSegment(text='First'), TextSegment(text='\n\n'), TextSegment(text='Next.')])
    assert p._char_position == len('First\n\nNext.')
    assert any(a.description == 'Gathering thoughts before new idea' for a in plan.actions)
