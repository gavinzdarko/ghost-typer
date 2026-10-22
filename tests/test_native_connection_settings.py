import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest


def callback_for(key, response):
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_make_connection_callback')
    scope = {'rumps': Mock(), 'save_settings_dict': Mock(), 'logger': Mock(), 'urlsplit': urlsplit}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<connection>', 'exec'), scope)
    target = SimpleNamespace(_settings_dict={'anthropic_api_key': 'prior-secret', 'wpm': 72},
                             _run_settings_window=Mock(return_value=response), orchestrator=Mock())
    return scope['_make_connection_callback'](target, key, 'Connection'), target, scope


def test_api_key_is_masked_and_never_prefilled_or_logged():
    callback, target, scope = callback_for('anthropic_api_key', SimpleNamespace(clicked=True, text=' new-secret '))
    callback(None)
    assert scope['rumps'].Window.call_args.kwargs['secure'] is True
    assert scope['rumps'].Window.call_args.kwargs['default_text'] == ''
    assert target._settings_dict == {'anthropic_api_key': 'new-secret', 'wpm': 72}
    assert 'new-secret' not in str(scope['logger'].mock_calls)
    target.orchestrator.update_settings.assert_called_once_with(target._settings_dict)


@pytest.mark.parametrize('response', [None, SimpleNamespace(clicked=False, text='discard')])
def test_cancel_or_unavailable_modal_preserves_existing_key(response):
    callback, target, scope = callback_for('anthropic_api_key', response)
    callback(None)
    assert target._settings_dict['anthropic_api_key'] == 'prior-secret'
    scope['save_settings_dict'].assert_not_called()


def test_blank_key_can_be_cleared():
    callback, target, scope = callback_for('anthropic_api_key', SimpleNamespace(clicked=True, text=''))
    callback(None)
    assert target._settings_dict['anthropic_api_key'] == ''


@pytest.mark.parametrize('key', ['anthropic_api_key', 'webhook_url'])
@pytest.mark.parametrize('error', [OSError('disk full'), ValueError('invalid config')])
def test_failed_connection_save_reports_failure_and_preserves_live_settings(key, error):
    value = 'new-secret' if key == 'anthropic_api_key' else 'https://example.com/hook'
    callback, target, scope = callback_for(key, SimpleNamespace(clicked=True, text=value))
    before = target._settings_dict.copy()
    scope['save_settings_dict'].side_effect = error
    callback(None)
    assert target._settings_dict == before
    target.orchestrator.update_settings.assert_not_called()
    target.orchestrator.notification_service.notify_error.assert_called_once()
    assert value not in str(scope['logger'].mock_calls)


@pytest.mark.parametrize('value', ['file:///tmp/webhook', 'not a url', 'https://[invalid'])
def test_invalid_webhook_is_not_saved(value):
    callback, target, scope = callback_for('webhook_url', SimpleNamespace(clicked=True, text=value))
    callback(None)
    scope['save_settings_dict'].assert_not_called()
    target.orchestrator.update_settings.assert_not_called()


def test_native_menu_exposes_the_connection_and_ocr_controls():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id in ('_NUMERIC_SETTINGS', '_TOGGLE_SETTINGS') for t in n.targets)]
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_build_settings_menu')
    scope = {'rumps': Mock()}
    exec(compile(ast.Module(body=assignments + [method], type_ignores=[]), '<menu>', 'exec'), scope)
    target = SimpleNamespace(_settings_dict={}, _settings_menu={}, _setting_items={},
                             _make_numeric_callback=Mock(), _make_toggle_callback=Mock(),
                             _make_connection_callback=Mock())
    scope['_build_settings_menu'](target)
    assert {'anthropic_api_key', 'webhook_url', 'verify_after_typing'} <= target._settings_menu.keys()
