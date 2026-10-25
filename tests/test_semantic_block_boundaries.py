import pytest

from src.text_parser import TextParser


@pytest.mark.parametrize('tag', ['main', 'aside', 'address', 'nav', 'figure', 'figcaption'])
def test_semantic_blocks_do_not_join_neighboring_words(tag):
    source = f'<{tag}>First article</{tag}><{tag}>Related content</{tag}>'
    assert ''.join(s.text for s in TextParser().parse(source, is_html=True)) == 'First article\n\nRelated content'


def test_semantic_blocks_retain_inline_adjacency_within_each_block():
    source = '<main>Hello<strong>world</strong></main><aside>Related<i>content</i></aside>'
    assert ''.join(s.text for s in TextParser().parse(source, is_html=True)) == 'Helloworld\n\nRelatedcontent'
