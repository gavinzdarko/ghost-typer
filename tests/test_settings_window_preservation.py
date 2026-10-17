from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.settings_ui import SettingsWindow


def test_widget_save_keeps_unexposed_and_newer_disk_settings():
    window = SettingsWindow()
    window._vars = {"wpm": Mock(), "ai_enabled": Mock()}
    window._vars["wpm"].get.return_value = 74.1
    window._vars["ai_enabled"].get.return_value = False
    saved = {"grammar_error_rate": .03, "punctuation_error_rate": .07,
             "sentence_pause_min": 1.2, "future_option": "preserved", "wpm": 60}
    window._window = Mock()
    window._on_save = Mock()
    with patch("src.settings_ui.load_settings_dict", return_value=saved), patch("src.settings_ui.save_settings_dict") as persist:
        window._save()
    expected = {**saved, "wpm": 74, "ai_enabled": False}
    persist.assert_called_once_with(expected)
    window._on_save.assert_called_once_with(expected)
    window._window.destroy.assert_called_once()
