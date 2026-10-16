import pytest
from src.models import Rewrite, Settings, TypeText
from src.typing_planner import TypingPlanner, _Chunk


def replay(actions):
    text = ''
    for action in actions:
        if isinstance(action, TypeText):
            text += action.text
        elif isinstance(action, Rewrite):
            text = text[:-action.delete_count] if action.delete_count else text
            text += replay(action.new_actions)
    return text


@pytest.mark.parametrize('suffix', ['', '.', ',next', ' next', '  next', '\tend', '!'])
def test_notice_after_space_only_consumes_actual_space(suffix):
    planner = TypingPlanner(Settings(error_rate=0, false_alarm_rate=0, rewrite_max_probability=0, rewrite_base_probability=0))
    planner.profile.misspelling.notice_after_space_probability = 1
    actions, count, _ = planner._plan_chunk(_Chunk('receive' + suffix), {'receive': ('recieve', 'receive')})
    assert replay(actions) == 'receive' + suffix
    assert count == len('receive' + suffix)
