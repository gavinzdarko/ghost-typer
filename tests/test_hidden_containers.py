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
    assert text('<span style="content-visibility:hidden; content-visibility:visible">Visible</span>') == 'Visible'
    assert text('<span style="content-visibility:hidden!important; content-visibility:visible">Hidden</span>') == ''


def test_nested_closed_details_do_not_expose_hidden_content():
    source = '<details open><summary>Outer</summary><details><summary>Inner</summary>Hidden</details></details>'
    assert text(source) == 'Outer\n\nInner'
