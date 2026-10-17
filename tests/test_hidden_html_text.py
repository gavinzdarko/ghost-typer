from src.text_parser import TextParser


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
