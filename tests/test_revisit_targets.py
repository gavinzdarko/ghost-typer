from src.models import TypeText
from src.planned_text import PlannedText
from src.typing_planner import TypingPlanner


def test_revisit_uses_exact_unique_span_and_returns_to_insertion_cursor():
    planner = TypingPlanner()
    text = 'Uneven lengths; x, punctuation! target phrase. ' + 'tail ' * 30
    actions = planner._build_revisit(text, 'target phrase', 'new wording is longer')
    assert actions
    # The user's existing prefix/suffix surround our insertion region.
    state = PlannedText('Existing document prefix. ' + text).apply(actions + [TypeText(text='NEXT')])
    assert state.valid
    assert state.text == 'Existing document prefix. ' + text.replace('target phrase', 'new wording is longer') + 'NEXT'
    assert state.cursor == len(state.text)


def test_missing_duplicate_and_unsafe_unicode_targets_are_noops():
    planner = TypingPlanner()
    for text, original in [('x ' * 100, 'missing'), ('word ' * 100, 'word'), ('e\u0301 ' + 'tail ' * 30, 'tail')]:
        assert planner._build_revisit(text, original, 'replacement') == []


def test_multiple_revisits_use_mutated_text_and_new_lengths():
    planner = TypingPlanner()
    planner.settings.revisit_probability = 1
    planner.profile.proofread.revisit_min_distance = 0
    class Rewriter:
        is_enabled = True
        def pick_revisit_targets(self, *_args, **_kwargs):
            return [{'original': 'one', 'revised': 'long first'}, {'original': 'three', 'revised': 'last'}]
    planner._ai_rewriter = Rewriter()
    actions = planner._maybe_build_revisit('one two three.', 3000)
    state = PlannedText('one two three.').apply(actions)
    assert state.valid
    assert state.text == 'long first two last.'


def test_distant_revision_is_skipped_instead_of_allocating_unbounded_key_actions():
    planner = TypingPlanner()
    text = 'target ' + 'tail ' * 20000
    assert planner._build_revisit(text, 'target', 'replacement') == []


def test_overlapping_occurrences_are_ambiguous_too():
    from src.planned_text import replace_known_span
    assert replace_known_span('banana', 'ana', 'other') == []
    assert replace_known_span('aaa', 'aa', 'b') == []
    assert replace_known_span('safe', ['invalid'], 'b') == []
