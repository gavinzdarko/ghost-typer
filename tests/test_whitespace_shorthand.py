"""Modern white-space shorthand retains the equivalent source whitespace."""
import pytest

from src.text_parser import TextParser


def text(source):
    return "".join(s.text for s in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize("mode", ["preserve", "preserve nowrap", "nowrap preserve",
                                 "preserve wrap", "wrap preserve", "break-spaces nowrap",
                                 "break-spaces wrap", "preserve nowrap none"])
def test_preserve_shorthands_keep_spaces_tabs_and_newlines(mode):
    source = "  keep  spaces\nnext\tline  "
    assert text(f'<span style="white-space:{mode}">{source}</span>') == source


@pytest.mark.parametrize("mode", ["preserve-breaks", "preserve-breaks wrap", "nowrap preserve-breaks"])
def test_preserve_breaks_shorthands_collapse_spaces_and_keep_newlines(mode):
    assert text(f'<span style="white-space:{mode}">  a  \n  b\t c </span>') == "a\nb c"


@pytest.mark.parametrize("mode", ["collapse", "collapse wrap", "nowrap collapse", "wrap", "none"])
def test_collapse_component_overrides_inherited_or_pre_defaults(mode):
    assert text(f'<pre style="white-space:{mode}">  a  \n b\tc </pre>') == "a b c"
    assert text(f'<div style="white-space:pre"><span style="white-space:{mode}">  a  \n b </span></div>') == "a b"


def test_shorthand_cascade_and_explicit_inheritance():
    assert text('<span style="white-space:preserve nowrap!important;white-space:normal">a  b</span>') == "a  b"
    assert text('<pre style="white-space:normal;white-space:preserve wrap">a  b\nc</pre>') == "a  b\nc"
    assert text('<span style="white-space:preserve nowrap"><span style="white-space:inherit"> a  b </span></span>') == " a  b "
    assert text('<pre><span style="white-space:collapse wrap;white-space:bogus!important">a  b</span></pre>') == "a b"
