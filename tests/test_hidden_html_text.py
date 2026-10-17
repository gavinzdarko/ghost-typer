from src.text_parser import TextParser
import pytest


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_hidden_subtrees_do_not_leak_or_invent_spaces():
    assert text('<p>Hello <span hidden>SECRET <b>nested</b></span>world</p>') == 'Hello world'
    assert text('<span>hel</span><span style="display: none">SECRET</span>lo') == 'hello'
    assert text('<div hidden="false"><p>SECRET</p></div>Visible') == 'Visible'


def test_inline_display_obeys_case_important_and_last_declaration():
    assert text('<span style="DISPLAY: NONE !IMPORTANT">secret</span>Visible') == 'Visible'
    assert text('<span style="display:none; display:inline">Visible</span>') == 'Visible'
    assert text('<span style="display:none!important; display:inline">secret</span>Visible') == 'Visible'


@pytest.mark.parametrize("attributes", ["hidden", 'style="display:none"',
    'style="DISPLAY: NONE !IMPORTANT; display:inline"'])
def test_preformatted_text_excludes_hidden_descendants_preserving_whitespace(attributes):
    html = f'<pre>  before<span {attributes}>SECRET<b hidden>nested</b></span>after\n  end</pre>'
    assert text(html) == '  beforeafter\n  end'


def test_preformatted_visible_display_override_and_nested_hidden_parent():
    assert text('<pre>A<span style="display:none; display:inline">B</span>C</pre>') == 'ABC'
    assert text('<div hidden><pre><span hidden>SECRET</span></pre></div>Visible') == 'Visible'
