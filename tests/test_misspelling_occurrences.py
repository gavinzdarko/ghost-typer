from src.models import Settings, TextSegment, TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def planner(misspellings):
    p = TypingPlanner(Settings(error_rate=0, false_alarm_rate=0,
                              rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    p._human_errors.process_text = lambda text: (text, misspellings)
    return p


def test_typo_targets_second_occurrence_without_lowercasing_first():
    text = 'The the end.'
    actions = planner([('teh', 'the', 4)]).plan([TextSegment(text)]).actions
    state = PlannedText().apply(actions)
    assert state.valid and state.text == text
    assert next(a for a in actions if isinstance(a, TypeText)).text == 'The '


def test_repeated_words_in_later_chunks_keep_separate_offsets_and_casing():
    text = 'The first sentence. The second sentence. The third sentence.'
    positions = [text.index('The', 1), text.rindex('The')]
    actions = planner([('teh', 'the', pos) for pos in positions]).plan([TextSegment(text)]).actions
    assert PlannedText().apply(actions).text == text
    assert sum(isinstance(a, TypeText) and a.text == 'teh' for a in actions) == 2
