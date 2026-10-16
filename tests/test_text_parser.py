from src.text_parser import TextParser


def test_plain_text_preserves_leading_indentation():
    source = "if ready:\n    launch()\n        report()"

    parsed = TextParser().parse(source)

    assert "".join(segment.text for segment in parsed) == source
