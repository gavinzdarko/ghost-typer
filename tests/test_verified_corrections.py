from src.models import Rewrite, TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner():
    p = TypingPlanner()
    p.profile.behaviors.final_proofread.probability = 1
    p.profile.behaviors.final_proofread.min_text_length = 0
    return p


def test_final_proofread_ignores_invented_or_ambiguous_errors():
    p = planner()
    p._behavioral_content = {'proofreading_fixes': [{'original': 'teh', 'fixed': 'the', 'position_fraction': 0.8}]}
    assert p._build_final_proofread('the text is already correct') == []
    assert p._build_final_proofread('teh twice teh') == []


def test_final_proofread_tracks_changed_lengths_and_insertion_cursor():
    p = planner()
    p._behavioral_content = {'proofreading_fixes': [
        {'original': 'teh', 'fixed': 'the longer', 'position_fraction': 1},
        {'original': 'wrng', 'fixed': 'right', 'position_fraction': 0},
    ]}
    text = 'teh uneven sentence, then wrng.'
    state = PlannedText('EXISTING: ' + text).apply(p._build_final_proofread(text) + [TypeText(text='END')])
    assert state.valid
    assert state.text == 'EXISTING: the longer uneven sentence, then right.END'


def test_autocorrect_ignores_estimates_and_requires_known_word():
    p = planner()
    assert p._build_autocorrect_fix('teh', 'the', 999) == []
    assert p._build_autocorrect_fix('teh', 'the', known_text='already the') == []
    text = 'first teh, followed by several oddly sized words'
    state = PlannedText('PREFIX ' + text).apply(p._build_autocorrect_fix('teh', 'the', 999, known_text=text))
    assert state.valid and state.text == 'PREFIX ' + text.replace('teh', 'the')
    assert state.cursor == len(state.text)


def test_deferred_autocorrect_replays_actual_mutated_output():
    p = planner()
    cfg = p.profile.behaviors.autocorrect
    cfg.min_words_back = cfg.max_words_back = 1
    p._behavioral_content = {'autocorrect_fixes': [{'word': 'teh', 'correct': 'the'}]}
    actions = [TypeText(text='teh')]
    p._track_autocorrect_words('teh', actions)
    assert p._autocorrect_count == 0
    actions.append(TypeText(text=' next'))
    p._track_autocorrect_words(' next', actions)
    state = PlannedText().apply(actions)
    assert state.valid and state.text == 'the next'
    # A rewrite already fixed it: the pending AI entry cannot edit another word.
    p = planner()
    p.profile.behaviors.autocorrect.min_words_back = p.profile.behaviors.autocorrect.max_words_back = 1
    p._behavioral_content = {'autocorrect_fixes': [{'word': 'teh', 'correct': 'the'}]}
    actions = [TypeText(text='teh')]
    p._track_autocorrect_words('teh', actions)
    actions.extend([Rewrite.simple(3, 'the'), TypeText(text=' next')])
    p._track_autocorrect_words(' next', actions)
    assert p._autocorrect_count == 0


def test_local_proofread_verifies_typo_and_handles_double_strike_deletion():
    p = planner()
    text = 'abcc def'
    actions = p._build_proofread([('c', '', 3), ('x', 'z', 1)], len(text), known_text=text)
    state = PlannedText('PRE ' + text).apply(actions)
    assert state.valid and state.text == 'PRE abc def'
    assert state.cursor == len(state.text)
