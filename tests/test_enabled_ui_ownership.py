"""Delayed enabled controls must describe the current session."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
    return app, queued


@pytest.mark.parametrize('enabled', [True, False])
def test_newer_menu_command_owns_enabled_controls(enabled):
    app, queued = target(enabled)
    method('_hotkey_toggle_enabled')(app)
    if enabled:
        # OFF must take effect before the GUI queue is serviced.
        app.orchestrator.disable.assert_called_once_with(blocking=False)
        assert not app.orchestrator.is_enabled
    method('_toggle')(app, app._toggle_item)
    assert app.orchestrator.is_enabled is enabled
    for callback in queued:
        callback()
    assert app._toggle_item.title == ('Turn OFF' if enabled else 'Turn ON')
    assert app.icon == ('idle' if enabled else 'off')
    assert app._status_item.title == ('Status: Idle' if enabled else 'Status: Off')


@pytest.mark.parametrize('state', [OrchestratorState.PLANNING, OrchestratorState.TYPING,
                                    OrchestratorState.PAUSED, OrchestratorState.VERIFYING])
def test_late_enabled_effect_does_not_replace_current_session_status(state):
    app, queued = target(True)
    method('_hotkey_toggle_enabled')(app)
    method('_toggle')(app, app._toggle_item)
    app.orchestrator.state = state
    app.icon = 'current session'
    app._status_item.title = 'current session'
    app._stop_animation.reset_mock()
    app._progress_overlay.reset_mock()
    for callback in queued:
        callback()
    assert app._toggle_item.title == 'Turn OFF'
    assert app.icon == 'current session'
    assert app._status_item.title == 'current session'
    app._stop_animation.assert_not_called()
    app._progress_overlay.hide.assert_not_called()


def test_reordered_hotkey_effects_render_latest_disabled_state():
    app, queued = target(False)
    method('_hotkey_toggle_enabled')(app)
    method('_hotkey_toggle_enabled')(app)
    assert not app.orchestrator.is_enabled
    for callback in reversed(queued):
        callback()
    assert app._toggle_item.title == 'Turn ON'
    assert app.icon == 'off'
    assert app._status_item.title == 'Status: Off'
