from src.text_parser import TextParser


def rendered(html):
    return "".join(segment.text for segment in TextParser().parse(html, is_html=True))


def test_consecutive_br_elements_preserve_visible_blank_lines():
    assert rendered("<p>A<br><br><br>B</p>") == "A\n\n\nB"
    assert rendered("<p>A<br> \n <br>B</p>") == "A\n\nB"


def test_explicit_breaks_at_document_edges_survive_block_cleanup():
    assert rendered("<p><br><br>A<br></p>") == "\n\nA\n"
    assert rendered("<p>A</p><p>B</p>") == "A\n\nB"


def test_consecutive_break_runs_materialize_linear_text_work(monkeypatch):
    from src import text_parser as module
    from src.models import TextSegment

    class MeasuredSegment(TextSegment):
        break_characters_written = 0

        def __setattr__(self, name, value):
            if name == "text" and isinstance(value, str) and value and not value.strip("\n"):
                type(self).break_characters_written += len(value)
            super().__setattr__(name, value)

    monkeypatch.setattr(module, "TextSegment", MeasuredSegment)
    count = 4000
    result = module.TextParser().parse("before" + "<br>" * count + "after", is_html=True)
    assert "".join(segment.text for segment in result) == "before" + "\n" * count + "after"
    # Count the actual intermediate newline representation writes, independent
    # of wall-clock speed. Repeated growing prefixes would write millions.
    assert MeasuredSegment.break_characters_written <= count * 3
