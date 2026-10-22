import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.orchestrator import OrchestratorState
from test_menu_planning_focus import delegate_method, target


def toggle_method(name="_pause_resume"):
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/menu_bar_app.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GhostTyperApp")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {"OrchestratorState": OrchestratorState, "rumps": SimpleNamespace(MenuItem=object)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<menu-toggle>", "exec"), scope)
    return scope[name]


def test_pause_click_takes_ownership_from_automatic_menu_pause():
    app = target()
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
    app = target()
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
    app = target()
    app.orchestrator._state = OrchestratorState.TYPING
    app.orchestrator._simulator = Mock()
    app._pause_resume = lambda sender: toggle_method()(app, sender)
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method("menuWillOpen_")(delegate, None)
    toggle_method("_hotkey_toggle_pause")(app)
    delegate_method("menuDidClose_")(delegate, None)
    assert app.orchestrator.state == OrchestratorState.PAUSED
    app.orchestrator._simulator.resume.assert_not_called()
