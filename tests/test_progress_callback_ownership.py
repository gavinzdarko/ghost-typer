import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.orchestrator import OrchestratorState


def progress_method():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/menu_bar_app.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GhostTyperApp")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_on_progress")
    scope = {"OrchestratorState": OrchestratorState}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<progress>", "exec"), scope)
    return scope["_on_progress"]


def app():
    queued = []
    target = SimpleNamespace(orchestrator=SimpleNamespace(state_snapshot=(OrchestratorState.TYPING, 1)),
        _status_item=SimpleNamespace(title="Status: Typing..."),
        _progress_overlay=Mock(), _run_on_main=queued.append,
        _queue_gui_update=lambda key, fn: queued.append(fn))
    return target, queued


def test_old_progress_cannot_overwrite_completion_or_subsequent_typing():
    for next_state in (OrchestratorState.IDLE, OrchestratorState.PAUSED, OrchestratorState.TYPING):
        target, queued = app()
        progress_method()(target, 20, 100, 10, 50)
        target.orchestrator.state_snapshot = next_state, 2
        target._status_item.title = "Current state"
        queued.pop()()
        assert target._status_item.title == "Current state"
        target._progress_overlay.update.assert_not_called()


def test_current_progress_updates_and_non_typing_progress_is_ignored():
    target, queued = app()
    progress_method()(target, 20, 100, 10, 50)
    queued.pop()()
    assert target._status_item.title == "Status: Typing... 20% (80 left)"
    target._progress_overlay.update.assert_called_once_with(20, 100, 10, 50)
    target.orchestrator.state_snapshot = OrchestratorState.IDLE, 2
    progress_method()(target, 100, 100)
    assert not queued
