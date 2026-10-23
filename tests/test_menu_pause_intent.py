import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.orchestrator import OrchestratorState
from test_menu_planning_focus import delegate_method, target


def toggle_method(name="_pause_resume"):
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/menu_bar_app.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GhostTyperApp")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {"OrchestratorState": OrchestratorState, "rumps": SimpleNamespace(MenuItem=object)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<menu-toggle>", "exec"), scope)
    return scope[name]


def app_target():
    app = target()
    app._pause_item = SimpleNamespace(title="Pause")
    app._run_on_main = lambda callback: callback()
    return app


def test_pause_click_takes_ownership_from_automatic_menu_pause():
    app = app_target()
    app.orchestrator._state = OrchestratorState.TYPING
    app.orchestrator._simulator = Mock()
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method("menuWillOpen_")(delegate, None)
    assert app._menu_auto_paused
    toggle_method()(app, None)
    delegate_method("menuDidClose_")(delegate, None)
    assert app.orchestrator.state == OrchestratorState.PAUSED
    app.orchestrator._simulator.resume.assert_not_called()


def test_resume_click_on_a_manual_pause_runs_only_after_menu_closes():
    app = app_target()
    app.orchestrator._state = OrchestratorState.PAUSED
    app.orchestrator._simulator = Mock()
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method("menuWillOpen_")(delegate, None)
    toggle_method()(app, None)
    assert app.orchestrator.state == OrchestratorState.PAUSED
    app.orchestrator._simulator.resume.assert_not_called()
    delegate_method("menuDidClose_")(delegate, None)
    assert app.orchestrator.state == OrchestratorState.TYPING
    app.orchestrator._simulator.resume.assert_called_once()


def test_f6_during_an_automatic_menu_pause_keeps_it_paused_after_dismissal():
    app = app_target()
    app.orchestrator._state = OrchestratorState.TYPING
    app.orchestrator._simulator = Mock()
    app._pause_resume = lambda sender: toggle_method()(app, sender)
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method("menuWillOpen_")(delegate, None)
    toggle_method("_hotkey_toggle_pause")(app)
    assert app._pause_item.title == "Resume"
    delegate_method("menuDidClose_")(delegate, None)
    assert app.orchestrator.state == OrchestratorState.PAUSED
    app.orchestrator._simulator.resume.assert_not_called()


@pytest.mark.parametrize('close_first', [False, True])
def test_f6_and_menu_close_are_serialized_without_losing_pause_intent(close_first):
    app = app_target()
    app.orchestrator._state = OrchestratorState.TYPING
    app.orchestrator._simulator = Mock()
    app._pause_resume = lambda sender: toggle_method()(app, sender)
    pending = []
    app._run_on_main = pending.append
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method('menuWillOpen_')(delegate, None)
    toggle_method('_hotkey_toggle_pause')(app)
    assert app._menu_auto_paused
    assert len(pending) == 1
    if close_first:
        delegate_method('menuDidClose_')(delegate, None)
    pending.pop()()
    if not close_first:
        delegate_method('menuDidClose_')(delegate, None)
    assert app.orchestrator.state == OrchestratorState.PAUSED
    assert not app._menu_auto_paused


@pytest.mark.parametrize('flag', ['_shutting_down', '_settings_modal_active'])
def test_delayed_hotkey_cannot_change_state_during_shutdown_or_settings(flag):
    app = app_target()
    app.orchestrator._state = OrchestratorState.TYPING
    app.orchestrator._simulator = Mock()
    app._pause_resume = lambda sender: toggle_method()(app, sender)
    pending = []
    app._run_on_main = pending.append
    toggle_method('_hotkey_toggle_pause')(app)
    setattr(app, flag, True)
    pending.pop()()
    assert app.orchestrator.state == OrchestratorState.TYPING
