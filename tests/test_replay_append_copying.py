from src.models import ApplyFormatting, PressKey, Settings, TextSegment, TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


class CountedText(str):
    copied = 0

    def __getitem__(self, index):
        return CountedText(super().__getitem__(index))

    def __add__(self, other):
        result = CountedText(super().__add__(other))
        CountedText.copied += len(result)
        return result


def test_many_appended_actions_do_not_copy_the_growing_string_each_time():
    CountedText.copied = 0
    state = PlannedText(CountedText('prefix'))
    state.apply([TypeText(text='x') for _ in range(10000)])
    assert state.text == 'prefix' + 'x' * 10000
    assert CountedText.copied <= 4 * len(state.text)


def test_buffer_flush_preserves_selection_and_middle_edits():
    state = PlannedText('a').apply([TypeText(text='bc'), PressKey(key='left'),
        ApplyFormatting(shortcut=('shift', 'right')), TypeText(text='D'), TypeText(text='e')])
    assert state.valid and state.text == 'abDe'
    assert len(state) == state.cursor == 4


def test_ordinary_chunks_do_not_read_the_full_emitted_prefix(monkeypatch):
    planner = TypingPlanner(Settings(error_rate=0, grammar_error_rate=0,
        punctuation_error_rate=0, false_alarm_rate=0, pause_frequency=0,
        rewrite_base_probability=0, rewrite_max_probability=0), ai_enabled=False)
    source = 'A sentence with several words. ' * 300
    observed = 0
    original = PlannedText.__getattribute__

    def counted(self, name):
        nonlocal observed
        value = original(self, name)
        if name == 'text':
            observed += len(value)
        return value

    monkeypatch.setattr(PlannedText, '__getattribute__', counted)
    plan = planner.plan([TextSegment(source)])
    assert PlannedText().apply(plan.actions).text == source
    assert observed <= 5 * len(source)
