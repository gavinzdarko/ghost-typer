from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_start_and_item_value_control_following_numbers():
    assert text('<ol start="4"><li>Four</li><li value="9">Nine</li><li>Ten</li></ol>') == '4. Four\n9. Nine\n10. Ten'


def test_reversed_lists_count_only_their_own_items():
    result = text('<ol reversed><li>Outer<ol><li>Inner</li></ol></li><li>Next</li></ol>')
    assert result.startswith('2. Outer')
    assert '1. Inner' in result
    assert '1. Next' in result
    assert text('<ol reversed start="7"><li>A</li><li value="3">B</li><li>C</li></ol>') == '7. A\n3. B\n2. C'


def test_invalid_numbers_fall_back_without_typing_markup():
    assert text('<ol start="bad"><li value="bad">A</li><li>B</li></ol>') == '1. A\n2. B'
