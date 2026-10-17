from unittest.mock import Mock

import pytest
from src.text_parser import TextParser


def test_deep_html_is_rejected_instead_of_typing_tags_and_metadata():
    html = "<head><title>Private metadata</title></head>" + "<span>" * 1200 + "Visible" + "</span>" * 1200
    with pytest.raises(ValueError, match="Copy as plain text"):
        TextParser().parse(html, is_html=True)


def test_parser_failure_does_not_feed_raw_html_to_plaintext_fallback():
    parser = TextParser()
    parser._parse_html = Mock(side_effect=RuntimeError("parser failed"))
    parser._parse_plain_text = Mock()
    with pytest.raises(ValueError, match="safely"):
        parser.parse("<script>secret</script><p>Hello</p>", is_html=True)
    parser._parse_plain_text.assert_not_called()


def test_intentionally_plain_text_can_still_contain_markup():
    original = "Write <span> as an example."
    assert "".join(s.text for s in TextParser().parse(original)) == original
