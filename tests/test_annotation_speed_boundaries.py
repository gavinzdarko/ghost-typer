from src.models import Pause, Settings, TextSegment, TypeText
from src.typing_planner import TypingPlanner


def planner():
    result = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_max_probability=0), ai_enabled=False)
    result.profile.behaviors.quote.source_glance_frequency = 0
    return result


def typed_speeds(plan):
    return [(char, action.speed_multiplier) for action in plan.actions
            if isinstance(action, TypeText) for char in action.text]


def test_quote_annotation_can_exclude_opening_and_closing_quotes():
    p = planner()
    text = '“quoted”'
    plan = p.plan([TextSegment(text)], behavioral_content={
        'quote_ranges': [{'start': 1, 'end': 7, 'type': 'direct_quote'}]})
    assert typed_speeds(plan) == [(char, .55 if 1 <= pos < 7 else 1)
                                 for pos, char in enumerate(text)]


def test_adjacent_composition_ranges_can_split_a_token():
    p = planner()
    text = 'abcdef'
    plan = p.plan([TextSegment(text)], behavioral_content={
        'composition_annotations': [
            {'start': 1, 'end': 3, 'mode': 'composition'},
            {'start': 3, 'end': 5, 'mode': 'copy'}]})
    assert typed_speeds(plan) == list(zip(text, [1, .8, .8, 1.1, 1.1, 1]))


def test_boundaries_preserve_syllable_pauses_and_word_speed():
    p = planner()
    text = 'example'
    plan = p.plan([TextSegment(text)], behavioral_content={
        'word_speed_map': [{'word': text, 'multiplier': 2}],
        'syllable_boundaries': [{'word': text, 'syllables': ['ex', 'am', 'ple']}],
        'quote_ranges': [{'start': 1, 'end': 4, 'type': 'direct_quote'}],
        'composition_annotations': [{'start': 3, 'end': 6, 'mode': 'copy'}]})
    assert typed_speeds(plan) == list(zip(text, [.5, .5, .5, .55, .55, .55, .5]))
    assert len([a for a in plan.actions if isinstance(a, Pause) and 0 < a.duration < .1]) == 2


def test_missing_annotations_keep_one_unmodified_text_action():
    p = planner()
    text = 'A plain sentence.'
    plan = p.plan([TextSegment(text)])
    assert typed_speeds(plan) == [(char, 1) for char in text]


def test_annotation_speed_covers_spaces_but_stops_at_exact_end():
    p = planner()
    text = 'a  b'
    plan = p.plan([TextSegment(text)], behavioral_content={
        'quote_ranges': [{'start': 1, 'end': 3, 'type': 'paraphrase_close'}]})
    assert typed_speeds(plan) == list(zip(text, [1, .75, .75, 1]))


def test_composition_clause_pause_uses_punctuation_position():
    p = planner()
    text = 'word,'
    plan = p.plan([TextSegment(text)], behavioral_content={
        'composition_annotations': [{'start': 4, 'end': 5, 'mode': 'composition'}]})
    assert typed_speeds(plan) == list(zip(text, [1, 1, 1, 1, .8]))
    assert any(a.description == 'Composing next clause' for a in plan.actions)


def test_annotation_splitting_constructs_linear_text_volume(monkeypatch):
    import src.typing_planner as module
    constructed_chars = 0

    class CountedTypeText(TypeText):
        def __post_init__(self):
            nonlocal constructed_chars
            constructed_chars += len(self.text)
            super().__post_init__()

    monkeypatch.setattr(module, 'TypeText', CountedTypeText)
    p = planner()
    p._behavioral_content = {'quote_ranges': [
        {'start': i, 'end': i + 1, 'type': 'direct_quote'} for i in range(1, 200, 2)]}
    text = 'abc ' * 5000
    actions = p._build_word_speed_actions(text)
    assert ''.join(a.text for a in actions if isinstance(a, TypeText)) == text
    assert constructed_chars <= 3 * len(text)
