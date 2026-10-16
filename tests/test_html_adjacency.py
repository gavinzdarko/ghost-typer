import pytest

from src.text_parser import TextParser


@pytest.mark.parametrize(('html', 'expected'), [
    ('pre<strong>fix</strong>', 'prefix'),
    ('<span>Hello</span><b>,</b><i> world</i>!', 'Hello, world!'),
    ('<span>Hello</span> <span>world</span>', 'Hello world'),
    ('<p>A <b> bold </b> word.</p>', 'A bold word.'),
    ('<p>first</p><p>second</p>', 'first\n\nsecond'),
    ('<span>a </span>  <i> b</i>', 'a b'),
])
def test_inline_nodes_preserve_only_source_whitespace(html, expected):
    assert ''.join(s.text for s in TextParser().parse(html, is_html=True)) == expected


@pytest.mark.parametrize('html', [
    '\n<p>first</p>\n<p>second</p>\n',
    '<div>\n  <p>first</p>\n  <p>second</p>\n</div>',
    '<p>first</p> <span> </span> <p>second</p>',
])
def test_source_indentation_between_blocks_is_not_an_extra_paragraph(html):
    assert ''.join(s.text for s in TextParser().parse(html, is_html=True)) == 'first\n\nsecond'


def test_preformatted_text_preserves_literal_whitespace():
    text = '    if ready:\n        launch()  '
    assert ''.join(s.text for s in TextParser().parse('<pre>' + text + '</pre>', is_html=True)) == text


def test_empty_visible_html_does_not_fall_back_to_typing_markup():
    assert TextParser().parse('<script>hidden()</script>\n  ', is_html=True) == []
