import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from src.settings_ui import parse_numeric_setting


@pytest.mark.parametrize("key,text,expected", [
    ("error_rate", "4%", .04), ("pause_frequency", " 8 % ", .08),
    ("error_rate", ".12", .12), ("start_delay", " 3.5s ", 3.5),
    ("wpm", "74", 74),
])
def test_display_units_are_parsed(key, text, expected):
    assert parse_numeric_setting(key, text) == expected


@pytest.mark.parametrize("key,text", [
    ("wpm", "0"), ("wpm", "65.5"), ("wpm", "60%"),
    ("error_rate", "4"), ("start_delay", "-1"),
    ("start_delay", "inf"), ("pause_frequency", "nan"),
    ("pause_duration_max", "100000"), ("error_rate", "2s"),
])
def test_invalid_values_are_rejected(key, text):
    with pytest.raises(ValueError):
        parse_numeric_setting(key, text)


def test_rejected_menu_value_does_not_mutate_or_persist_settings():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/menu_bar_app.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GhostTyperApp")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_make_numeric_callback")
    scope = {"rumps": Mock(), "parse_numeric_setting": parse_numeric_setting,
             "save_settings_dict": Mock(), "logger": Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<menu>", "exec"), scope)
    scope["rumps"].Window.return_value.run.return_value = SimpleNamespace(clicked=True, text="5s")
    settings = {"pause_duration_min": .3, "pause_duration_max": 4}
    app = SimpleNamespace(_settings_dict=settings.copy(), orchestrator=Mock(),
                          _run_settings_window=lambda window: window.run())
    callback = scope["_make_numeric_callback"](app, "pause_duration_min", "Pause Min", float, str)
    callback(None)
    assert app._settings_dict == settings
    scope["save_settings_dict"].assert_not_called()
    app.orchestrator.update_settings.assert_not_called()


def test_numeric_disk_failure_preserves_menu_and_reports_save_error():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_make_numeric_callback')
    scope = {'rumps': Mock(), 'parse_numeric_setting': parse_numeric_setting,
             'save_settings_dict': Mock(side_effect=OSError('disk full')), 'logger': Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<menu>', 'exec'), scope)
    target = SimpleNamespace(_settings_dict={'wpm': 60}, orchestrator=Mock(),
                             _run_settings_window=Mock(return_value=SimpleNamespace(clicked=True, text='70')))
    scope['_make_numeric_callback'](target, 'wpm', 'WPM', int, str)(None)
    assert target._settings_dict == {'wpm': 60}
    target.orchestrator.update_settings.assert_not_called()
    target.orchestrator.notification_service.notify_error.assert_called_once()
    assert 'Could not save' in target.orchestrator.notification_service.notify_error.call_args.args[0]
