import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(s.text for s in TextParser().parse(source, is_html=True))


def test_closed_details_include_only_the_first_direct_summary():
    source = '<details><summary>Visible <b>title</b></summary>Closed content<summary>Hidden second title</summary></details>'
    assert text(source) == 'Visible title'


def test_closed_details_without_direct_summary_do_not_expose_body():
    assert text('<details><div><summary>Hidden title</summary>Hidden body</div></details>') == ''


def test_hiding_first_summary_does_not_promote_another_summary():
    assert text('<details><summary hidden>Hidden</summary><summary>Also hidden</summary></details>') == ''


def test_open_details_preserve_their_content_and_block_boundaries():
    assert text('<details open><summary>Title</summary>Visible body</details>') == 'Title\n\nVisible body'


def test_content_visibility_hidden_hides_descendants_without_losing_block_boundary():
    source = 'Before<div style="content-visibility:hidden"><span style="visibility:visible">Hidden</span></div>After'
    assert text(source) == 'Before\n\nAfter'


def test_content_visibility_uses_declaration_order_and_important():
    assert text('<div style="content-visibility:hidden; content-visibility:visible">Visible</div>') == 'Visible'
    assert text('<div style="content-visibility:hidden!important; content-visibility:visible">Hidden</div>') == ''


def test_nested_closed_details_do_not_expose_hidden_content():
    source = '<details open><summary>Outer</summary><details><summary>Inner</summary>Hidden</details></details>'
    assert text(source) == 'Outer\n\nInner'


def test_content_visibility_does_not_hide_default_inline_text():
    assert text('Before<span style="content-visibility:hidden">Visible</span>After') == 'BeforeVisibleAfter'


@pytest.mark.parametrize('display', ['inline', 'contents', 'table', 'table-row', 'table-cell', 'ruby'])
def test_content_visibility_does_not_hide_boxes_that_cannot_have_size_containment(display):
    assert text(f'<div style="display:{display};content-visibility:hidden">Visible</div>') == 'Visible'


@pytest.mark.parametrize('display', ['block', 'inline-block', 'inline flow-root', 'flex', 'grid'])
def test_content_visibility_hides_containment_capable_inline_display_overrides(display):
    assert text(f'<span style="display:{display};content-visibility:hidden">Hidden</span>') == ''


def test_content_visibility_display_override_honors_important_and_inherit():
    assert text('<span style="display:inline-block!important;display:inline;content-visibility:hidden">Hidden</span>') == ''
    assert text('<div><span style="display:inherit;content-visibility:hidden">Hidden</span></div>') == ''
