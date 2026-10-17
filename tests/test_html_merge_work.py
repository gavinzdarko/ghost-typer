import re
from unittest.mock import patch

from src.models import TextSegment
from src.text_parser import TextParser


def test_many_inline_nodes_require_linear_whitespace_scanning():
    segments = [TextSegment(text='word ', formatting={}) for _ in range(20_000)]
    scanned = 0
    sub = re.sub

    def measured(pattern, replacement, value, *args, **kwargs):
        nonlocal scanned
        scanned += len(value)
        return sub(pattern, replacement, value, *args, **kwargs)

    with patch('src.text_parser.re.sub', side_effect=measured):
        result = TextParser._clean_segments(segments)
    assert ''.join(segment.text for segment in result) == ' '.join(['word'] * 20_000)
    assert scanned <= sum(len(segment.text) for segment in segments) * 2


def test_merge_preserves_inline_adjacency_and_preformatted_boundaries():
    html = '<p>hel<b>lo</b> <i> world</i></p><pre> a  b\n  c</pre><p>Next</p>'
    text = ''.join(segment.text for segment in TextParser().parse(html, is_html=True))
    assert text == 'hello world\n\n a  b\n  c\n\nNext'
