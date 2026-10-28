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


@pytest.mark.parametrize("display", ["contents", "inline", "inline-block"])
def test_generated_item_boundaries_do_not_add_enters_at_document_edges(display):
    assert text(f'<ul style="display:{display}"><li>one</li><li>two</li></ul>') == "- one\n- two"
    assert text(f'<ol style="display:{display}"><li>one</li></ol>') == "1. one"
    assert text(f'<ul style="display:{display}"><li>one<br></li></ul>') == "- one\n"


def test_standalone_item_has_no_generated_edge_newlines():
    assert text('<li>one</li>') == "- one"


@pytest.mark.parametrize("display", ["block", "flow-root", "flex", "grid"])
def test_block_item_override_keeps_boundaries_without_a_list_marker(display):
    assert text(f'before<ul><li style="display:{display}">one</li></ul>after') == "before\none\nafter"


def test_inline_list_item_still_generates_its_marker():
    assert text('<ul style="display:inline"><li style="display:inline list-item">one</li>'
                '<li style="display:inline list-item">two</li></ul>') == "- one- two"


def test_items_without_markers_do_not_advance_or_reset_ordered_counters():
    assert text('<ol><li style="display:inline">one</li><li>two</li></ol>') == "one\n1. two"
    assert text('<ol start="4"><li style="display:block" value="100">one</li><li>two</li></ol>') == "one\n4. two"
    assert text('<ol><li>one</li><li style="display:contents" value="100">two</li><li>three</li></ol>') == "1. one\ntwo\n2. three"


def test_reversed_default_counts_only_actual_list_item_boxes():
    assert text('<ol reversed><li style="display:inline">one</li><li>two</li><li>three</li></ol>') == "one\n2. two\n1. three"
    assert text('<ol reversed start="9"><li style="display:contents" value="100">one</li><li>two</li></ol>') == "one\n9. two"


def test_display_inheritance_priority_and_nested_lists():
    assert text('before<ul style="display:contents"><li style="display:inherit">one</li></ul>after') == "beforeoneafter"
    assert text('<ul style="display:inline"><li style="display:inline!important;display:list-item">one</li></ul>') == "one"
    assert text('<ul style="display:inline"><li style="display:inline"><ol><li>nested</li></ol></li></ul>') == "1. nested"
    assert text('<ol start="4"><li style="display:revert">one</li><li>two</li></ol>') == "4. one\n5. two"
