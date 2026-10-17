from src.text_parser import TextParser


def text(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_head_metadata_is_excluded_from_fragments_without_body():
    html = '<html><head><title>Private title</title><style>secret CSS</style></head><p>Visible</p></html>'
    assert text(html) == "Visible"


def test_standalone_metadata_does_not_leak_into_visible_content():
    assert text('<title>Private</title><meta content="secret"><span>Hello</span>') == "Hello"
    assert text('<head><title>Private</title></head>') == ""
