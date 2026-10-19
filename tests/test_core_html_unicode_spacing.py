import pytest

from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


@pytest.mark.parametrize("space", ["\u00a0", "\u2002", "\u2003", "\u2009", "\u202f"])
def test_rendered_unicode_spacing_is_preserved_between_inline_nodes(space):
    assert text("<b>10</b>" + space + "<i>000</i>") == "10" + space + "000"
    assert text("<p>" + space + "</p>") == space
    assert text("<p>" + space + "word" + space + "</p>") == space + "word" + space


def test_character_references_keep_nonbreaking_and_typographic_spaces():
    assert text("<p>&nbsp;thin&thinsp;em&emsp;end&nbsp;</p>") == "\u00a0thin\u2009em\u2003end\u00a0"


def test_ascii_source_indentation_still_collapses_between_words():
    assert text("<p>one\n  <b>two</b>\t three</p>") == "one two three"
