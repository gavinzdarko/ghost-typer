import json

from src.ai_planner import AIPlanner


def test_prefaced_plan_can_contain_braces_quotes_and_escapes_in_source():
    planner = AIPlanner(enabled=False)
    for text in ('a } closes a brace', 'a { opens a brace', 'escaped "quote" and \\ path', '{"nested": "source"}'):
        data = {"segments": [{"text": text, "actions": [{"type": "type", "text": text}]}]}
        response = "Here is the plan:\n" + json.dumps(data) + "\nDone."
        assert planner._parse_json_response(response) == data


def test_invalid_preface_braces_do_not_hide_the_valid_plan():
    data = {"segments": []}
    assert AIPlanner(enabled=False)._parse_json_response('Note: {not JSON}\n' + json.dumps(data)) == data
