import pytest

from src.text_parser import TextParser


def plain(html):
    return ''.join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_inert_template_content_never_enters_the_typing_source():
    assert plain('start<template><p>secret draft</p></template>end') == 'startend'


@pytest.mark.parametrize('style', [
    'visibility:hidden', 'visibility:collapse',
    'visibility:hidden!important;visibility:visible',
    'visibility:visible;VISIBILITY: hidden ! important',
])
def test_invisible_text_is_removed_without_inserting_spaces(style):
    assert plain(f'start<span style="{style}">secret</span>end') == 'startend'


def test_descendants_can_restore_visibility_even_inside_preformatted_text():
    assert plain('<pre style="visibility:hidden">secret<span style="visibility:visible">visible</span>hidden</pre>') == 'visible'
    assert plain('<span style="visibility:hidden">secret<b style="visibility:visible">shown</b></span>') == 'shown'


def test_visible_override_cannot_escape_display_none_or_hidden_attribute():
    assert plain('<p>start<span hidden><b style="visibility:visible">secret</b></span>end</p>') == 'startend'
