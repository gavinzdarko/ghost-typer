from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_alphabetic_markers_include_multiple_letters_and_case():
    assert text('<ol type="a" start="26"><li>one</li><li>two</li></ol>') == "z. one\naa. two"
    assert text('<ol type="A"><li>one</li><li>two</li></ol>') == "A. one\nB. two"


def test_roman_markers_reversed_values_and_item_override():
    assert text('<ol type="i" start="5" reversed><li>one</li><li>two</li></ol>') == "v. one\niv. two"
    assert text('<ol type="I"><li value="9">one</li><li type="a">two</li><li>three</li></ol>') == "IX. one\nj. two\nXI. three"


def test_unsupported_marker_type_and_out_of_range_use_decimal():
    assert text('<ol type="unsupported"><li>one</li></ol>') == "1. one"
    assert text('<ol type="a" start="0"><li>zero</li></ol>') == "0. zero"
