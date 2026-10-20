import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.ai_planner import AIPlanner
from src.models import MakeMistake, Rewrite, Settings, TextSegment, TypeText


def test_ai_plan_enforces_disabled_typos_and_rewrites_without_retry():
    planner = AIPlanner(Settings(error_rate=0, rewrite_max_probability=0), enabled=False)
    planner._enabled = True
    planner._client = Mock()
    planner._client.messages.create.return_value = SimpleNamespace(
        stop_reason='end_turn', content=[SimpleNamespace(text=json.dumps({
            'segments': [{'text': 'Hello world.', 'actions': [
                {'type': 'mistake', 'wrong': 'Helo', 'correct': 'Hello '},
                {'type': 'rewrite', 'first_attempt': 'earth.', 'final_version': 'world.'},
            ]}],
        }))])
    plan = planner.plan([TextSegment('Hello world.')])
    assert plan.metadata['ai_generated']
    assert ''.join(action.text for action in plan.actions if isinstance(action, TypeText)) == 'Hello world.'
    assert not any(isinstance(action, (MakeMistake, Rewrite)) for action in plan.actions)
    planner._client.messages.create.assert_called_once()
    prompt = planner._client.messages.create.call_args.kwargs['messages'][0]['content']
    assert 'Include 0 typos and 0 rewrites' in prompt


def test_enabled_ai_edit_controls_keep_temporary_actions():
    planner = AIPlanner(enabled=False)
    assert isinstance(planner._convert_action({'type': 'mistake', 'wrong': 'teh', 'correct': 'the'})[0][0], MakeMistake)
    assert any(isinstance(action, Rewrite) for action in planner._convert_action(
        {'type': 'rewrite', 'first_attempt': 'old', 'final_version': 'new'})[0])
