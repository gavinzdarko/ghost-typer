"""CSS comments and string contents cannot reveal invisible clipboard text."""
import pytest

from src.text_parser import TextParser


def text(source):
    return "".join(s.text for s in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize("rule", [
    "display:/* comment */none", "/* lead */display:none/* tail */",
    "display/**/:/**/none", "visibility:/* comment */hidden",
    "display:none!/**/important;display:inline",
    "visibility:hidden!important;visibility:visible/* !important */",
    "display:none/* unfinished",
])
def test_commented_hidden_rules_remove_their_text(rule):
    assert text(f'before<span style="{rule}">secret</span>after') == "beforeafter"


def test_comments_preserve_block_and_whitespace_modes():
    assert text('before<span style="display:/**/block">middle</span>after') == "before\nmiddle\n\nafter"
    assert text('<div style="content-visibility:/**/hidden">secret</div>') == ""
    assert text('<span style="white-space:/**/pre"> a  b\n c</span>') == " a  b\n c"


@pytest.mark.parametrize("rule", [
    "content:';display:none';display:inline",
    "--rules:{display:none;visibility:hidden};display:inline",
    "background:url(';display:none');display:inline",
    "content:'/*';display:inline",
    r"content:'escaped\';display:none';display:inline",
    "display:n/**/one", "dis/**/play:none",
])
def test_rule_like_strings_groups_and_split_identifiers_do_not_hide_text(rule):
    assert text(f'<span style="{rule}">visible</span>') == "visible"


def test_commented_declarations_keep_priority_and_source_order():
    assert text('<span style="display:none;/* comment */display:inline">visible</span>') == "visible"
    assert text('<span style="visibility:visible;/* comment */visibility:hidden">secret</span>') == ""
    assert text('<span style="white-space:normal;/* comment */white-space:pre">a  b</span>') == "a  b"
