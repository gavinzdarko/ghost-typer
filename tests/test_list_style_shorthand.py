import pytest

from src.text_parser import TextParser


def text(style, *, tag='ul'):
    source = f'<{tag} style="{style}"><li>A</li><li>B</li></{tag}>'
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('style', ['list-style:none', 'list-style:inside none',
                                  'list-style:none outside', 'list-style:none none',
                                  'LIST-STYLE:/**/NONE ! important'])
def test_shorthand_none_suppresses_inherited_markers(style):
    assert text(style) == 'A\nB'
    assert text(style, tag='ol') == 'A\nB'


@pytest.mark.parametrize('value, expected', [
    ('inside lower-alpha', 'a. A\nb. B'),
    ('upper-roman outside', 'I. A\nII. B'),
    ('none decimal', '1. A\n2. B'),
    ('decimal none', '1. A\n2. B'),
    ('inside', '- A\n- B'),
])
def test_literal_shorthand_sets_type_or_resets_omitted_type(value, expected):
    assert text(f'list-style-type:none;list-style:{value}') == expected


@pytest.mark.parametrize('style, expected', [
    ('list-style:none;list-style-type:decimal', '1. A\n2. B'),
    ('list-style-type:decimal;list-style:none', 'A\nB'),
    ('list-style:none!important;list-style-type:decimal', 'A\nB'),
    ('list-style-type:decimal!important;list-style:none', '1. A\n2. B'),
    ('list-style:decimal!important;list-style:none!important', 'A\nB'),
])
def test_longhand_and_shorthand_share_declaration_order_and_priority(style, expected):
    assert text(style) == expected


@pytest.mark.parametrize('value', ['bogus', 'none bogus', 'inside outside',
                                  'decimal square', 'inside inside',
                                  'none none none', 'decimal none none',
                                  'inherit none', '"none"'])
def test_invalid_shorthand_does_not_override_an_earlier_valid_type(value):
    assert text(f'list-style-type:decimal;list-style:{value}!important') == '1. A\n2. B'


def test_global_values_follow_existing_inheritance_and_reset_rules():
    assert text('list-style:none;list-style:initial', tag='ol') == '- A\n- B'
    assert text('list-style:none;list-style:revert', tag='ol') == '1. A\n2. B'
    source = '<ol style="list-style:none"><li style="list-style:inherit">A</li><li>B</li></ol>'
    assert ''.join(segment.text for segment in TextParser().parse(source, is_html=True)) == 'A\nB'


def test_comments_and_quoted_declarations_cannot_introduce_shorthand_rules():
    assert text('list-style-type:decimal;/*list-style:none*/content:\'list-style:none\'') == '1. A\n2. B'
