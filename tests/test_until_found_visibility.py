"""Author content visibility can override the hidden-until-found UA default."""
import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('value', ['visible', 'initial', 'auto', 'unset', 'inherit'])
@pytest.mark.parametrize('hidden', ['until-found', 'UNTIL-FOUND'])
def test_inline_content_visibility_restores_until_found_text(value, hidden):
    source = (f'<p>Before</p><div hidden="{hidden}" '
              f'style="display:block;content-visibility:{value}">'
              'Visible payload</div><p>After</p>')
    assert text(source) == 'Before\n\nVisible payload\n\nAfter'


@pytest.mark.parametrize('style', [
    'content-visibility:hidden;content-visibility:visible',
    'content-visibility:visible!important;content-visibility:hidden',
    'content-visibility:visible;content-visibility:bogus!important',
    'content-visibility:hidden;CONTENT-VISIBILITY:/**/VISIBLE ! important',
    'content-visibility:visible!important;content-visibility:revert',
])
def test_until_found_restoration_uses_valid_inline_cascade(style):
    assert text(f'<div hidden="until-found" style="{style}">Visible</div>') == 'Visible'


@pytest.mark.parametrize('style', [
    '', 'display:block', 'content-visibility:hidden',
    'content-visibility:bogus', 'content-visibility:revert',
    'content-visibility:revert-layer',
    'content-visibility:visible;content-visibility:hidden',
    'content-visibility:hidden!important;content-visibility:visible',
    'content-visibility:visible;content-visibility:revert!important',
    'content-visibility:visible;content-visibility:revert-layer!important',
])
def test_unrestored_until_found_text_stays_hidden(style):
    assert text(f'A<div hidden="until-found" style="{style}">Secret</div>B') == 'AB'


@pytest.mark.parametrize('style', [
    'display:none;content-visibility:visible',
    'display:none!important;display:block;content-visibility:initial',
    'visibility:hidden;content-visibility:visible',
])
def test_restoring_content_visibility_does_not_override_other_hiding(style):
    assert 'Secret' not in text(f'<div hidden="until-found" style="{style}">Secret</div>')


def test_until_found_descendant_cannot_restore_a_skipped_parent():
    assert text('A<div hidden="until-found"><span style="content-visibility:visible">Secret</span></div>B') == 'AB'


def test_until_found_inherit_uses_parent_computed_value_even_for_inline_boxes():
    source = ('<span style="content-visibility:hidden">Before'
              '<span hidden="until-found" style="display:inline-block;content-visibility:inherit">'
              'Secret</span>After</span>')
    # The parent's inline box cannot skip its own text, but its computed hidden
    # value can be inherited by a containment-capable descendant.
    assert text(source) == 'BeforeAfter'
    assert text(source.replace('content-visibility:hidden', 'content-visibility:initial')) == 'BeforeSecretAfter'


def test_restored_until_found_container_keeps_other_hidden_descendants_hidden():
    source = ('<div hidden="until-found" style="content-visibility:visible">'
              'A<span hidden>Secret</span><span hidden="until-found">Secret</span>B</div>')
    assert text(source) == 'AB'


def test_content_visibility_alone_does_not_restore_ordinary_hidden_or_closed_dialog():
    assert text('<div hidden style="content-visibility:visible">Secret</div>') == ''
    assert text('<dialog hidden="until-found" style="content-visibility:visible">Secret</dialog>') == ''
