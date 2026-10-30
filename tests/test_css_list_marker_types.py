from src.text_parser import TextParser


def text(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


def test_inherited_none_suppresses_markers_without_removing_list_boundaries():
    assert text('<ul style="list-style-type:none"><li>one</li><li>two</li></ul>') == 'one\ntwo'
    assert text('<ol><li style="list-style-type:none">one</li><li>two</li></ol>') == 'one\n2. two'
    assert text('<ol reversed><li style="list-style-type:none" value="7">one</li><li>two</li></ol>') == 'one\n6. two'


def test_css_marker_types_override_container_html_type_and_work_on_unordered_lists():
    for marker_type, expected in [('decimal', '1. one\n2. two'),
                                  ('lower-alpha', 'a. one\nb. two'),
                                  ('upper-alpha', 'A. one\nB. two'),
                                  ('lower-roman', 'i. one\nii. two'),
                                  ('upper-roman', 'I. one\nII. two')]:
        assert text(f'<ol type="A" style="list-style-type:{marker_type}"><li>one</li><li>two</li></ol>') == expected
        assert text(f'<ul style="list-style-type:{marker_type}"><li>one</li><li>two</li></ul>') == expected


def test_own_item_type_and_css_cascade_take_priority_over_inherited_style():
    assert text('<ol style="list-style-type:none"><li type="a">one</li>'
                '<li type="I" style="list-style-type:lower-alpha">two</li></ol>') == 'a. one\nb. two'
    assert text('<ol style="list-style-type:lower-alpha!important;list-style-type:decimal">'
                '<li>one</li><li style="list-style-type:upper-roman;list-style-type:bogus!important">two</li></ol>') == 'a. one\nII. two'
    assert text('<ul style="list-style-type:/**/none"><li>one</li></ul>') == 'one'


def test_global_values_and_nested_lists_keep_element_defaults():
    assert text('<ol style="list-style-type:none"><li style="list-style-type:initial">one</li>'
                '<li style="list-style-type:unset">two</li><li style="list-style-type:inherit">three</li></ol>') == '- one\ntwo\nthree'
    assert text('<ol style="list-style-type:none"><li>one<ol><li>inner</li></ol></li><li>two</li></ol>') == 'one\n1. inner\ntwo'
    assert text('<ul style="list-style-type:lower-alpha"><li>one</li>'
                '<li style="display:inline">inline</li><li>two</li></ul>') == 'a. one\ninline\nb. two'


def test_value_hint_only_resets_ordered_list_counters():
    assert text('<ul style="list-style-type:decimal"><li value="99">one</li><li>two</li></ul>') == '1. one\n2. two'
    assert text('<ol style="list-style-type:decimal"><li value="99">one</li><li>two</li></ol>') == '99. one\n100. two'
