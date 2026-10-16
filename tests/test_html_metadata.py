from src.text_parser import TextParser


def test_comments_and_document_metadata_never_become_typed_text():
    html = '<!DOCTYPE html><?hidden private?><p>Hello<!-- confidential data --> world.</p>'
    text = ''.join(segment.text for segment in TextParser().parse(html, is_html=True))
    assert text.strip() == 'Hello world.'
    assert 'confidential' not in text
    assert 'private' not in text


def test_comment_between_inline_nodes_does_not_invent_spacing():
    html = '<b>hel</b><!-- hidden -->lo'
    assert ''.join(segment.text for segment in TextParser().parse(html, is_html=True)) == 'hello'
