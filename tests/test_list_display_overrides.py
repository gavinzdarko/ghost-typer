"""List-specific text generation follows explicit inline display roles."""
import pytest

from src.text_parser import TextParser


def text(source):
    return "".join(s.text for s in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize("container", ["ul", "ol"])
@pytest.mark.parametrize("display", ["contents", "inline", "inline-block"])
def test_inline_list_containers_and_items_do_not_invent_markers_or_breaks(container, display):
    assert text(f'before<{container} style="display:{display}">'
                '<li style="display:inline">one</li><li style="display:inline">two</li>'
                f'</{container}>after') == "beforeonetwoafter"


def test_list_container_contents_keeps_default_child_list_item_boxes():
    assert text('before<ol style="display:contents"><li>one</li><li>two</li></ol>after') == "before\n1. one\n2. two\nafter"


@pytest.mark.parametrize("display", ["block", "flow-root", "flex", "grid"])
def test_block_item_override_keeps_boundaries_without_a_list_marker(display):
    assert text(f'before<ul><li style="display:{display}">one</li></ul>after') == "before\none\nafter"


def test_inline_list_item_still_generates_its_marker():
    assert text('<ul style="display:inline"><li style="display:inline list-item">one</li>'
                '<li style="display:inline list-item">two</li></ul>') == "- one- two"


def test_display_inheritance_priority_and_nested_lists():
    assert text('before<ul style="display:contents"><li style="display:inherit">one</li></ul>after') == "beforeoneafter"
    assert text('<ul style="display:inline"><li style="display:inline!important;display:list-item">one</li></ul>') == "one"
    assert text('<ul style="display:inline"><li style="display:inline"><ol><li>nested</li></ol></li></ul>') == "1. nested"
    assert text('<ol start="4"><li style="display:revert">one</li><li>two</li></ol>') == "4. one\n5. two"
