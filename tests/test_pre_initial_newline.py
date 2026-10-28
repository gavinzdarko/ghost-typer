"""Match HTML's one-initial-LF rule without trimming preserved code."""
import pytest

from src.text_parser import TextParser


def text(source):
    return "".join(s.text for s in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_one_initial_newline_is_ignored(newline):
    assert text(f"<pre>{newline}alpha\n beta</pre>") == "alpha\n beta"
    assert text(f"<pre>{newline}{newline}alpha</pre>") == "\nalpha"


@pytest.mark.parametrize("source,expected", [
    ("<pre>  alpha\n beta</pre>", "  alpha\n beta"),
    ("<pre><span>\nalpha</span></pre>", "\nalpha"),
    ("<pre><!-- comment -->\nalpha</pre>", "\nalpha"),
    ("<pre><br>\nalpha</pre>", "\n\nalpha"),
    ("<pre>\n</pre>", ""),
    ("<pre>\n\n</pre>", "\n"),
    ("<span style='white-space:pre'>\nalpha</span>", "\nalpha"),
])
def test_other_code_whitespace_and_child_boundaries_remain(source, expected):
    assert text(source) == expected
