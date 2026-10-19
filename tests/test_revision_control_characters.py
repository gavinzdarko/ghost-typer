import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.ai_planner import AIRewriter
from src.planned_text import PlannedText, replace_known_span


@pytest.mark.parametrize("control", ["\t", "\n", "\r", "\b", "\x00", "\x1b", "\x7f"])
def test_relative_replacement_rejects_navigation_and_control_characters(control):
    text = "Some earlier phrase followed by a long ordinary tail."
    assert replace_known_span(text, "earlier phrase", "revised" + control + "phrase") == []


def test_ai_revisit_response_filters_controls_before_planning():
    rewriter = AIRewriter(enabled=False)
    rewriter._enabled = True
    rewriter._client = Mock()
    text = "Some earlier phrase followed by a long ordinary tail to review."
    targets = [
        {"original": "earlier phrase", "revised": "revised\tphrase"},
        {"original": "ordinary tail", "revised": "ordinary ending"},
    ]
    rewriter._client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text=json.dumps(targets))])
    assert rewriter.pick_revisit_targets(text) == targets[1:]


def test_printable_revision_still_returns_to_the_insertion_endpoint():
    text = "Some earlier phrase followed by a long ordinary tail."
    state = PlannedText(text).apply(replace_known_span(text, "earlier phrase", "revised phrase"))
    assert state.valid
    assert state.text == text.replace("earlier phrase", "revised phrase")
    assert state.cursor == len(state.text)
