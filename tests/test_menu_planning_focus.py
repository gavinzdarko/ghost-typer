import ast
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from orchestrator_support import Orchestrator
from src.orchestrator import OrchestratorState


def delegate_method(name):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_MenuDelegate')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {'OrchestratorState': OrchestratorState, 'logger': Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<delegate>', 'exec'), scope)
    return scope[name]


def target():
    orch = Orchestrator.__new__(Orchestrator)
    orch._state = OrchestratorState.PLANNING
    orch._state_revision = 0
    orch._state_lock = threading.Lock()
    orch._session_lock = threading.RLock()
    orch.on_state_change = None
    orch.notification_service = Mock()
    return SimpleNamespace(orchestrator=orch, _shutting_down=False, _menu_auto_paused=False)


def test_menu_held_open_pauses_new_simulator_before_typing_is_published():
    app = target()
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method('menuWillOpen_')(delegate, None)
    sim = Mock()
    transitions = []
    app.orchestrator.on_state_change = lambda state: transitions.append((state, sim.pause.called))
    with patch('src.orchestrator.KeystrokeSimulator', return_value=sim):
        assert app.orchestrator._activate_simulator() is sim
    assert transitions == [(OrchestratorState.PAUSED, True)]
    app.orchestrator.resume()
    assert app.orchestrator.state == OrchestratorState.PAUSED
    sim.resume.assert_not_called()
    delegate_method('menuDidClose_')(delegate, None)
    assert app.orchestrator.state == OrchestratorState.TYPING
    sim.resume.assert_called_once()


def test_menu_closed_before_planning_finishes_does_not_pause_future_typing():
    app = target()
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method('menuWillOpen_')(delegate, None)
    delegate_method('menuDidClose_')(delegate, None)
    sim = Mock()
    with patch('src.orchestrator.KeystrokeSimulator', return_value=sim):
        app.orchestrator._activate_simulator()
    assert app.orchestrator.state == OrchestratorState.TYPING
    sim.pause.assert_not_called()


def test_menu_opened_while_idle_resumes_a_newly_ready_session():
    app = target()
    app.orchestrator._state = OrchestratorState.IDLE
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method('menuWillOpen_')(delegate, None)
    app.orchestrator.state = OrchestratorState.PLANNING
    sim = Mock()
    with patch('src.orchestrator.KeystrokeSimulator', return_value=sim):
        app.orchestrator._activate_simulator()
    assert app.orchestrator.state == OrchestratorState.PAUSED
    delegate_method('menuDidClose_')(delegate, None)
    assert app.orchestrator.state == OrchestratorState.TYPING
    sim.resume.assert_called_once()


def test_preexisting_manual_pause_is_not_resumed_when_menu_closes():
    app = target()
    app.orchestrator._state = OrchestratorState.PAUSED
    app.orchestrator._simulator = Mock()
    delegate = SimpleNamespace(_app_ref=app)
    delegate_method('menuWillOpen_')(delegate, None)
    delegate_method('menuDidClose_')(delegate, None)
    assert app.orchestrator.state == OrchestratorState.PAUSED
    app.orchestrator._simulator.resume.assert_not_called()


def test_worker_activating_while_menu_open_callback_runs_keeps_menu_pause_ownership():
    app = target()
    delegate = SimpleNamespace(_app_ref=app)
    original = app.orchestrator.set_menu_open
    sim = Mock()

    def activate_before_callback_continues(value):
        result = original(value)
        if value:
            with patch('src.orchestrator.KeystrokeSimulator', return_value=sim):
                app.orchestrator._activate_simulator()
        return result

    app.orchestrator.set_menu_open = activate_before_callback_continues
    delegate_method('menuWillOpen_')(delegate, None)
    assert app.orchestrator.state == OrchestratorState.PAUSED
    delegate_method('menuDidClose_')(delegate, None)
    assert app.orchestrator.state == OrchestratorState.TYPING
    sim.resume.assert_called_once()
