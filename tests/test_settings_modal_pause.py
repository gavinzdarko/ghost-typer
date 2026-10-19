import ast
from contextlib import contextmanager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from src.orchestrator import OrchestratorState


def modal_method():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_run_settings_window')
    scope = {'OrchestratorState': OrchestratorState}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<modal>', 'exec'), scope)
    return scope['_run_settings_window']


def app(state):
    orch = Mock(state=state, _simulator=object())
    orch.clipboard_monitor.suspended.return_value = nullcontext()
    orch.pause.side_effect = lambda: setattr(orch, 'state', OrchestratorState.PAUSED)
    return SimpleNamespace(orchestrator=orch)


def test_typing_stays_paused_for_the_entire_dialog():
    target = app(OrchestratorState.TYPING)
    window = Mock()
    window.run.side_effect = lambda: target.orchestrator.state
    assert modal_method()(target, window) == OrchestratorState.PAUSED
    target.orchestrator.resume.assert_called_once()


@pytest.mark.parametrize('state', [OrchestratorState.PLANNING, OrchestratorState.VERIFYING])
def test_non_typing_workers_cannot_start_keys_inside_a_settings_dialog(state):
    target = app(state)
    window = Mock()
    assert modal_method()(target, window) is None
    window.run.assert_not_called()


def test_manual_pause_and_cancelled_sessions_are_not_resumed():
    for state in (OrchestratorState.PAUSED, OrchestratorState.TYPING):
        target = app(state)
        window = Mock()
        window.run.side_effect = lambda: setattr(target.orchestrator, 'state', OrchestratorState.IDLE)
        modal_method()(target, window)
        target.orchestrator.resume.assert_not_called()


def test_dialog_failure_restores_only_the_owned_pause():
    target = app(OrchestratorState.TYPING)
    window = Mock()
    window.run.side_effect = RuntimeError('dialog failed')
    with pytest.raises(RuntimeError):
        modal_method()(target, window)
    target.orchestrator.resume.assert_called_once()
    assert target._settings_modal_active is False


def test_paste_that_wins_the_clipboard_lock_blocks_modal_opening():
    target = app(OrchestratorState.IDLE)
    @contextmanager
    def pending_paste():
        target.orchestrator.state = OrchestratorState.PLANNING
        yield
    target.orchestrator.clipboard_monitor.suspended.side_effect = pending_paste
    window = Mock()
    assert modal_method()(target, window) is None
    window.run.assert_not_called()


@pytest.mark.parametrize('name', ['_hotkey_toggle_pause', '_hotkey_paste'])
def test_hotkeys_do_not_resume_or_launch_typing_inside_modal_settings(name):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'OrchestratorState': OrchestratorState}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<hotkey>', 'exec'), scope)
    target = SimpleNamespace(_shutting_down=False, _settings_modal_active=True, orchestrator=Mock())
    scope[name](target)
    assert target.orchestrator.mock_calls == []
