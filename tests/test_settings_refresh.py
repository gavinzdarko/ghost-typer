from unittest.mock import Mock, patch

from orchestrator_support import Orchestrator


def test_offline_settings_and_key_replacements_refresh_every_planner():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False}), patch('src.settings_ui.get_api_key', return_value=''), patch('anthropic.Anthropic', return_value=Mock()):
        app = Orchestrator()
        app.update_settings({'ai_enabled': False, 'wpm': 91, 'error_rate': .07, 'grammar_error_rate': .02})
        assert app.fallback_planner.settings.wpm == 91
        assert app.fallback_planner.engine.settings.wpm == 91
        assert app.fallback_planner._human_errors.misspelling_rate == .07
        assert app.fallback_planner._human_errors.grammar_error_rate == .02
        assert app.ai_profile_generator.settings.wpm == 91
        for key in ('first-key', 'changed-key', ''):
            app.update_settings({'ai_enabled': True, 'anthropic_api_key': key})
            assert app.ai_planner._api_key == key
            assert app.ai_rewriter._api_key == key
            assert app.fallback_planner._human_errors._api_key == key
            assert app.ai_profile_generator.is_enabled == bool(key)
            assert app.ai_planner.is_enabled == bool(key)
            assert app.fallback_planner._human_errors.is_enabled == bool(key)
        app.update_settings({'ai_enabled': False, 'anthropic_api_key': 'configured'})
        assert not app.ai_planner.is_enabled
        assert not app.ai_rewriter.is_enabled
        assert not app.ai_profile_generator.is_enabled
        assert not app.fallback_planner._human_errors.is_enabled


def test_startup_and_update_use_same_configured_key_then_environment_precedence():
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'environment-key'}), patch('anthropic.Anthropic', return_value=Mock()) as client:
        with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': True, 'anthropic_api_key': 'saved-key'}):
            app = Orchestrator()
        assert app.ai_planner._api_key == 'saved-key'
        assert app.fallback_planner._human_errors._api_key == 'saved-key'
        app.update_settings({'ai_enabled': True, 'anthropic_api_key': ''})
        assert app.ai_planner._api_key == 'environment-key'
        assert app.ai_rewriter._api_key == 'environment-key'
        assert app.fallback_planner._human_errors._api_key == 'environment-key'
        client.reset_mock()
        app.update_settings({'ai_enabled': False, 'anthropic_api_key': ''})
        client.assert_not_called()
        assert not app.ai_profile_generator.is_enabled
        assert not app.fallback_planner._human_errors.is_enabled


def test_clearing_configured_key_without_environment_removes_every_paid_client():
    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': ''}), patch('anthropic.Anthropic', return_value=Mock()):
        with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': True, 'anthropic_api_key': 'saved-key'}):
            app = Orchestrator()
        assert app.ai_planner.is_enabled
        app.update_settings({'ai_enabled': True, 'anthropic_api_key': ''})
        assert not app.ai_planner.is_enabled
        assert not app.ai_rewriter.is_enabled
        assert not app.ai_profile_generator.is_enabled
        assert not app.fallback_planner._human_errors.is_enabled
