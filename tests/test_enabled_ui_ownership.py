"""Delayed enabled controls must describe the current session."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from threading import Thread, current_thread

import pytest

from src.orchestrator import OrchestratorState


def method(name):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'GhostTyperApp')
    node = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    scope = {'rumps': SimpleNamespace(MenuItem=object), 'OrchestratorState': OrchestratorState,
             'ICON_OFF': 'off', 'ICON_IDLE': 'idle'}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<enabled controls>', 'exec'), scope)
    return scope[name]


def target(enabled):
    queued = []
    orchestrator = SimpleNamespace(is_enabled=enabled, state=OrchestratorState.IDLE)
    orchestrator.enable = Mock(side_effect=lambda: setattr(orchestrator, 'is_enabled', True))
    orchestrator.disable = Mock(side_effect=lambda **_: setattr(orchestrator, 'is_enabled', False))
    app = SimpleNamespace(orchestrator=orchestrator, _shutting_down=False,
        _settings_modal_active=False, _toggle_item=SimpleNamespace(title='Turn OFF' if enabled else 'Turn ON'),
        _status_item=SimpleNamespace(title='Status: Idle' if enabled else 'Status: Off'),
        icon='idle' if enabled else 'off', _stop_animation=Mock(),
        _progress_overlay=Mock(), _run_on_main=queued.append)
    app._toggle = lambda sender: method('_toggle')(app, sender)
    return app, queued


@pytest.mark.parametrize('enabled', [True, False])
def test_newer_menu_command_owns_enabled_controls(enabled):
    app, queued = target(enabled)
    method('_hotkey_toggle_enabled')(app)
    # Workers admit intent; enabled state is chosen in the GUI turn.
    app.orchestrator.enable.assert_not_called()
    app.orchestrator.disable.assert_not_called()
    method('_toggle')(app, app._toggle_item)
    assert app.orchestrator.is_enabled is (not enabled)
    for callback in queued:
        callback()
    assert app._toggle_item.title == ('Turn OFF' if enabled else 'Turn ON')
    assert app.icon == ('idle' if enabled else 'off')
    assert app._status_item.title == ('Status: Idle' if enabled else 'Status: Off')


@pytest.mark.parametrize('guard', ['_shutting_down', '_settings_modal_active'])
def test_pending_toggle_respects_new_shutdown_or_modal_guard(guard):
    app, queued = target(True)
    method('_hotkey_toggle_enabled')(app)
    setattr(app, guard, True)
    for callback in queued:
        callback()
    assert app.orchestrator.is_enabled
    app.orchestrator.disable.assert_not_called()


def test_overlapping_worker_toggles_are_decided_on_gui_thread():
    app, queued = target(True)
    operations = []
    def set_enabled(enabled):
        operations.append(current_thread())
        app.orchestrator.is_enabled = enabled
    app.orchestrator.enable.side_effect = lambda: set_enabled(True)
    app.orchestrator.disable.side_effect = lambda **_: set_enabled(False)
    workers = [Thread(target=lambda: method('_hotkey_toggle_enabled')(app)) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    assert not operations
    assert app.orchestrator.is_enabled
    assert len(queued) == 2
    for callback in queued:
        callback()
    assert app.orchestrator.is_enabled
    assert operations == [current_thread(), current_thread()]
    assert app._toggle_item.title == 'Turn OFF'
    assert app.icon == 'idle'


def test_reordered_hotkey_effects_render_latest_disabled_state():
    app, queued = target(False)
    method('_hotkey_toggle_enabled')(app)
    method('_hotkey_toggle_enabled')(app)
    app.orchestrator.enable.assert_not_called()
    app.orchestrator.disable.assert_not_called()
    for callback in reversed(queued):
        callback()
    assert app._toggle_item.title == 'Turn ON'
    assert app.icon == 'off'
    assert app._status_item.title == 'Status: Off'
