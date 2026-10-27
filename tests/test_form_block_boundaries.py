import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(s.text for s in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('tag', ['form', 'search', 'fieldset', 'legend', 'hgroup'])
def test_default_form_blocks_separate_neighboring_words(tag):
    assert text(f'Before<{tag}>Middle</{tag}>After') == 'Before\nMiddle\n\nAfter'


def test_open_dialog_preserves_surrounding_block_boundaries():
    assert text('Before<dialog open>Middle</dialog>After') == 'Before\nMiddle\n\nAfter'


def test_form_block_keeps_inline_adjacency_and_nested_legend_boundaries():
    assert text('<form>in<b>side</b></form>') == 'inside'
    assert text('<fieldset><legend>Label</legend>Body</fieldset>') == 'Label\n\nBody'


def test_hidden_form_container_does_not_create_a_boundary():
    assert text('Before<form hidden>Hidden</form>After') == 'BeforeAfter'
