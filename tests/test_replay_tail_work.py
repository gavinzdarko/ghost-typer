import pytest

from src.models import ApplyFormatting, PressKey, Rewrite, TypeText
from src.planned_text import PlannedText


def test_repeated_endpoint_corrections_do_not_materialize_the_growing_prefix():
    class CountedReplay(PlannedText):
        materialized_chars = 0

        @property
        def text(self):
            result = super().text
            self.materialized_chars += len(result)
            return result

    state = CountedReplay()
    for _ in range(10_000):
        state.apply([TypeText(text='x'), Rewrite.simple(1, 'a')])
    assert state.materialized_chars == 0
    assert state.valid and state.cursor == len(state) == 10_000
    assert state.text == 'a' * 10_000


@pytest.mark.parametrize('deleted,expected', [(1, 'base abcd!'), (3, 'base ab!'),
                                             (5, 'base !'), (7, 'bas!'), (10, '!')])
def test_tail_deletions_cross_buffered_pieces_and_materialized_prefix(deleted, expected):
    state = PlannedText('base ')
    state.apply([TypeText(text='ab'), TypeText(text='c'), TypeText(text='de'),
                 Rewrite.simple(deleted, '!')])
    assert state.valid and state.text == expected
    assert state.cursor == len(state) == len(expected)


def test_typo_markers_survive_or_disappear_with_the_edited_tail():
    state = PlannedText(track_typos=True)
    state.apply([TypeText(text='teh ', proofread_typo=('teh', 'the', 0)),
                 TypeText(text='wrng', proofread_typo=('wrng', 'wrong', 0)),
                 Rewrite.simple(4, 'right')])
    assert state.text == 'teh right'
    assert state.typos == [('teh', 'the', 0)]
    state.apply([PressKey(key='backspace')])
    assert state.text == 'teh righ'
    assert state.typos == [('teh', 'the', 0)]


def test_mid_document_selection_replacement_still_preserves_the_tail():
    state = PlannedText().apply([TypeText(text='abcdef'), PressKey(key='left'),
                                 PressKey(key='left'), ApplyFormatting(shortcut=('shift', 'right')),
                                 TypeText(text='!')])
    assert state.valid and state.text == 'abcd!f'
    assert state.cursor == 5 and state.anchor is None
