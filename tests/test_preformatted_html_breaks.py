from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_preformatted_breaks_preserve_lines_and_inline_adjacency():
    assert text("<pre>a<br>b<br><br>c</pre>") == "a\nb\n\nc"
    assert text("<pre>a<b>b</b><br> c</pre>") == "ab\n c"


def test_hidden_preformatted_breaks_do_not_restore_hidden_content():
    assert text('<pre>a<span hidden><br>x</span><br>b</pre>') == "a\nb"
