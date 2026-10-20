import pytest

from src.typing_planner import TypingPlanner


@pytest.mark.parametrize('separator', ['  ', '\t ', ' \t\t'])
def test_sentence_and_phrase_boundaries_preserve_all_separator_characters(separator):
    planner = TypingPlanner(ai_enabled=False)
    sentence = 'First.' + separator + 'Second.'
    chunks = planner._break_into_chunks(sentence)
    assert [chunk.text for chunk in chunks] == ['First.' + separator, 'Second.']
    assert chunks[0].is_sentence_end
    assert ''.join(chunk.text for chunk in chunks) == sentence
    phrase = 'One,' + separator + 'two.'
    assert planner._split_into_phrases(phrase) == ['One,' + separator, 'two.']


def test_trailing_spaces_are_not_a_new_sentence():
    planner = TypingPlanner(ai_enabled=False)
    assert [chunk.text for chunk in planner._break_into_chunks('One.   ')] == ['One.   ']
