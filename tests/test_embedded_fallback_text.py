import pytest

from src.text_parser import TextParser


def text(source):
    return ''.join(segment.text for segment in TextParser().parse(source, is_html=True))


@pytest.mark.parametrize('tag', ['iframe', 'canvas', 'audio', 'video'])
def test_embedded_fallback_is_not_visible_clipboard_text(tag):
    assert text(f'before<{tag}>SECRET <b>draft</b></{tag}>after') == 'beforeafter'


@pytest.mark.parametrize('tag', ['iframe', 'canvas', 'audio', 'video'])
def test_embedded_fallback_cannot_restore_visibility_or_add_block_breaks(tag):
    assert text(f'<pre>  before<{tag}><div style="visibility:visible;display:block">'
                f'SECRET</div></{tag}>after\n  end</pre>') == '  beforeafter\n  end'


def test_visible_fallback_for_an_unresolved_object_is_preserved():
    # Unlike supported media/canvas, OBJECT fallback can be rendered when its
    # resource fails. Do not fetch resources or assume this content is hidden.
    assert text('before<object><b>fallback</b></object>after') == 'beforefallbackafter'


def test_explicit_surrounding_whitespace_is_preserved():
    assert text('before <video>hidden</video> after') == 'before after'


def test_embedded_html_is_still_literal_in_plain_text_mode():
    source = '<canvas>literal markup</canvas>'
    assert TextParser().parse(source)[0].text == source
