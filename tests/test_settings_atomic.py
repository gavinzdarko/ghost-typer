import json
import stat
from unittest.mock import patch

import pytest
from src import settings_ui


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_ui, 'SETTINGS_DIR', tmp_path)
    monkeypatch.setattr(settings_ui, 'SETTINGS_FILE', tmp_path / 'settings.json')
    settings_ui.save_settings_dict({'wpm': 60})
    return settings_ui.SETTINGS_FILE


def test_serialization_failure_keeps_working_settings(settings_file):
    with pytest.raises(ValueError):
        settings_ui.save_settings_dict({'wpm': float('nan')})
    assert json.loads(settings_file.read_text()) == {'wpm': 60}


def test_replace_failure_keeps_working_settings_and_removes_temp(settings_file):
    with patch.object(settings_ui.os, 'replace', side_effect=OSError('disk error')):
        with pytest.raises(OSError):
            settings_ui.save_settings_dict({'wpm': 90})
    assert json.loads(settings_file.read_text()) == {'wpm': 60}
    assert list(settings_file.parent.iterdir()) == [settings_file]


def test_settings_and_api_key_are_owner_only(settings_file):
    settings_file.chmod(0o644)
    settings_ui.save_settings_dict({'anthropic_api_key': 'test-secret'})
    assert stat.S_IMODE(settings_file.stat().st_mode) == 0o600
