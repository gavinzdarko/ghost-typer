from src.text_parser import TextParser


def rendered(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_consecutive_br_elements_preserve_visible_blank_lines():
    assert rendered("<p>A<br><br><br>B</p>") == "A\n\n\nB"
    assert rendered("<p>A<br> \n <br>B</p>") == "A\n\nB"


def test_explicit_breaks_at_document_edges_survive_block_cleanup():
    assert rendered("<p><br><br>A<br></p>") == "\n\nA\n"
    assert rendered("<p>A</p><p>B</p>") == "A\n\nB"
