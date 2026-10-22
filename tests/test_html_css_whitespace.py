from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_css_preformatted_modes_keep_spaces_tabs_and_lines():
    for mode in ("pre", "pre-wrap", "break-spaces"):
        assert text(f'<div style="white-space:{mode}">a  b\n c\td</div>') == "a  b\n c\td"


def test_css_whitespace_is_inherited_and_normal_can_restore_collapsing():
    assert text('<div style="white-space:pre-wrap">a<span>  b\nc</span>d</div>') == "a  b\ncd"
    assert text('<div style="white-space:pre-wrap">a<span style="white-space:normal">  b\nc</span>d</div>') == "a b cd"


def test_css_whitespace_respects_inline_cascade_and_importance():
    assert text('<div style="white-space:pre-wrap!important;white-space:normal">a  b</div>') == "a  b"
    assert text('<div style="white-space:pre;white-space:normal">a  b</div>') == "a b"
