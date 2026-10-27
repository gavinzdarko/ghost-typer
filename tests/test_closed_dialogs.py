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
