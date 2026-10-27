"""Invalid inline literals must not mask earlier valid clipboard rules."""
import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('invalid', ['bogus', 'bogus !important', 'hidden visible', 'hidden !important extra'])
@pytest.mark.parametrize('prop', ['visibility', 'content-visibility'])
def test_invalid_visibility_declarations_do_not_expose_hidden_text(prop, invalid):
    source = f'Before<div style="{prop}:hidden;{prop}:{invalid}">Secret</div>After'
    assert 'Secret' not in text(source)
    assert text(source) == 'Before\n\nAfter'


@pytest.mark.parametrize('invalid', ['bogus', 'bogus !important', 'normal pre', 'normal !important extra'])
def test_invalid_whitespace_declarations_do_not_restore_pre_default(invalid):
    assert text(f'<pre style="white-space:normal;white-space:{invalid}">a  b\n c</pre>') == 'a b c'


@pytest.mark.parametrize('prop', ['visibility', 'content-visibility'])
def test_valid_visibility_rules_keep_declaration_order_and_priority(prop):
    assert text(f'<div style="{prop}:hidden!important;{prop}:visible">Secret</div>') == ''
    assert text(f'<div style="{prop}:hidden;{prop}:visible!important">Visible</div>') == 'Visible'
    assert text(f'<div style="{prop}:hidden!important;{prop}:visible!important">Visible</div>') == 'Visible'


def test_valid_whitespace_rules_keep_declaration_order_and_priority():
    assert text('<pre style="white-space:normal!important;white-space:pre">a  b</pre>') == 'a b'
    assert text('<pre style="white-space:normal!important;white-space:pre!important">a  b</pre>') == 'a  b'


@pytest.mark.parametrize('prop', ['visibility', 'content-visibility'])
def test_invalid_only_style_preserves_default_visibility(prop):
    assert text(f'<div style="{prop}:bogus!important">Visible</div>') == 'Visible'


def test_invalid_only_whitespace_preserves_inherited_preformatted_text():
    assert text('<pre><span style="white-space:bogus!important">a  b\n c</span></pre>') == 'a  b\n c'
