from src.models import Settings, TextSegment, TypeText, PressKey
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def offline_planner():
    return TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, rewrite_max_probability=0,
        rewrite_base_probability=0, proofread_probability=1))


def test_autocorrect_length_change_cannot_retarget_pending_typo():
    p = offline_planner()
    p.profile.behaviors.autocorrect.min_words_back = 2
    p.profile.behaviors.autocorrect.max_words_back = 2
    p.profile.behaviors.final_proofread.enabled = False
    p._pick_mistake_positions = lambda text: {0} if text.startswith('m ') else set()
    p._build_mistake = lambda *_: ([TypeText(text='n')], 1, ('n', 'm'))
    plan = p.plan([TextSegment('m teh, hello next.')], behavioral_content={
        'autocorrect_fixes': [{'word': 'teh', 'correct': 'the answer'}]})
    state = PlannedText().apply(plan.actions)
    assert state.valid
    assert state.text == 'm the answer, hello next.'


def test_local_typo_anchor_survives_earlier_autocorrect_length_change():
    p = offline_planner()
    p.profile.behaviors.autocorrect.min_words_back = p.profile.behaviors.autocorrect.max_words_back = 2
    p._pick_mistake_positions = lambda text: {6}
    p._build_mistake = lambda text, pos: ([TypeText(text='c')], 1, ('c', 'a'))
    plan = p.plan([TextSegment('wont cat dog')], behavioral_content={
        'autocorrect_fixes': [{'word': 'wont', 'correct': "won't"}],
    })
    actual = PlannedText().apply(plan.actions)
    assert actual.valid
    assert actual.text == "won't cat dog"


def test_double_strike_correction_sends_an_actual_deletion_event():
    p = offline_planner()
    actions = p._build_proofread([('c', '', 3)], 8, known_text='abcc def')
    assert any(isinstance(a, PressKey) and a.key == 'backspace' for a in actions)
    assert PlannedText('abcc def').apply(actions).text == 'abc def'
