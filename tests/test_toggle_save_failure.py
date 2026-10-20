import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def callback(settings, persist):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_make_toggle_callback')
    scope = {'save_settings_dict': persist, 'logger': Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<toggle>', 'exec'), scope)
    app = SimpleNamespace(_settings_dict=settings.copy(), orchestrator=Mock())
    return app, scope['_make_toggle_callback'](app, 'ai_enabled')


@pytest.mark.parametrize('error', [OSError('disk full'), ValueError('invalid config')])
def test_failed_save_keeps_live_configuration_and_menu_unchanged(error):
    persist = Mock(side_effect=error)
    app, toggle = callback({'ai_enabled': True, 'wpm': 60}, persist)
    sender = SimpleNamespace(state=1)
    toggle(sender)
    assert sender.state == 1
    assert app._settings_dict == {'ai_enabled': True, 'wpm': 60}
    app.orchestrator.update_settings.assert_not_called()
    app.orchestrator.notification_service.notify_error.assert_called_once()


def test_success_publishes_the_saved_candidate():
    persist = Mock()
    app, toggle = callback({'ai_enabled': True, 'wpm': 60}, persist)
    sender = SimpleNamespace(state=1)
    toggle(sender)
    expected = {'ai_enabled': False, 'wpm': 60}
    persist.assert_called_once_with(expected)
    app.orchestrator.update_settings.assert_called_once_with(expected)
    assert app._settings_dict == expected
    assert sender.state == 0
