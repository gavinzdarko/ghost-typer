import pytest
from src.text_parser import TextParser


@pytest.mark.parametrize('text', [
    'Use items[1] and values[a].',
    'Sources [1][2] support the claim.',
    'First paragraph\n\n[1]\n\nSecond paragraph',
    'Expected answers: [a], [b], [c].',
    '[edit] is literal text, as is [note 1].',
])
def test_plain_text_keeps_bracketed_content_and_paragraphs(text):
    assert ''.join(segment.text for segment in TextParser().parse(text)) == text
