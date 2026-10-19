import pytest

from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


@pytest.mark.parametrize("removed", ["<script>private()</script>",
    "<style>.private { color: red }</style>", "<noscript>private</noscript>",
    "<meta name='private' content='secret'>"])
def test_nonrendered_html_does_not_invent_an_inline_space(removed):
    assert text("hel" + removed + "lo") == "hello"
    assert text("hello " + removed + "world") == "hello world"


def test_removed_citation_does_not_separate_word_and_punctuation():
    assert text("<p>Evidence<sup class='reference'>[1]</sup>, supported.</p>") == "Evidence, supported."


def test_removed_citation_keeps_real_source_separators():
    assert text("<p>Evidence<sup>[1]</sup> supports this.</p>") == "Evidence supports this."
