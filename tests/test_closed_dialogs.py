import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(s.text for s in TextParser().parse(source, is_html=True))


def test_closed_dialog_does_not_type_its_nonrendered_body():
    assert text('Before<dialog>Hidden <b>body</b></dialog>After') == 'BeforeAfter'
    assert text('<dialog><p>Hidden</p></dialog><p>Visible</p>') == 'Visible'


def test_open_dialog_remains_visible_unless_explicitly_hidden():
    assert text('<dialog open>Visible</dialog>') == 'Visible'
    assert text('<dialog open style="display:none">Hidden</dialog>') == ''
    assert text('<dialog open hidden>Hidden</dialog>') == ''


def test_inline_display_can_reveal_a_closed_dialog():
    assert text('<dialog style="display:block">Visible</dialog>') == 'Visible'
    assert text('<dialog style="display:none;display:block">Visible</dialog>') == 'Visible'
    assert text('<dialog style="display:block!important;display:none">Visible</dialog>') == 'Visible'


@pytest.mark.parametrize('display', ['revert', 'revert-layer'])
def test_reverted_dialog_display_restores_its_html_default(display):
    assert text(f'<dialog style="display:{display}">Hidden</dialog>') == ''
    assert text(f'<dialog open style="display:{display}">Visible</dialog>') == 'Visible'


@pytest.mark.parametrize('style', ['display:bogus', 'display:none;display:bogus',
                                  'display:bogus!important', 'display:table bogus',
                                  'display:block inline', 'display:inline ruby list-item'])
def test_invalid_display_cannot_reveal_closed_dialog_text(style):
    assert text(f'Before<dialog style="{style}">Hidden</dialog>After') == 'BeforeAfter'


def test_invalid_important_declaration_does_not_override_valid_display():
    assert text('<dialog style="display:block;display:bogus!important">Visible</dialog>') == 'Visible'
    assert text('<dialog open style="display:none;display:bogus!important">Hidden</dialog>') == ''


@pytest.mark.parametrize('style', ['display:block;display:bogus!important', 'display:flex block',
                                  'display:block flex', 'display:flow-root list-item'])
def test_invalid_or_reordered_display_does_not_reveal_skipped_contents(style):
    assert 'Secret' not in text(f'A<div style="{style};content-visibility:hidden">Secret</div>B')


def test_inline_content_visibility_uses_valid_selected_display():
    assert text('A<span style="display:inline;display:bogus!important;content-visibility:hidden">Visible</span>B') == 'AVisibleB'
