from unittest.mock import Mock, patch
from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.models import TextSegment, TypingPlan


def app():
    with patch('src.orchestrator.load_settings_dict', return_value={'ai_enabled': False, 'start_delay': 4.25}), patch('src.settings_ui.get_api_key', return_value=''):
        target = Orchestrator()
    target.notification_service = Mock()
    target.fallback_planner = Mock()
    target.fallback_planner.plan.return_value = TypingPlan()
    target.text_parser.parse = Mock(return_value=[TextSegment('cell')])
    target._cell_has_content = Mock(return_value=False)
    target._execute_plan = Mock()
    return target


def test_start_delay_precedes_all_normal_and_table_keys():
    for table in (False, True):
        target = app()
        events = []
        target._cancel_event.wait = Mock(side_effect=lambda delay: events.append(('delay', delay)) or False)
        with patch('src.orchestrator.KeystrokeSimulator', side_effect=lambda: events.append(('simulator', None)) or Mock()) as simulator:
            if table:
                target._table_fill_pipeline([ClipboardContent('cell')])
            else:
                target._typing_pipeline(ClipboardContent('cell'))
            assert events[:2] == [('delay', 4.25), ('simulator', None)]
            target._execute_plan.assert_called_once()


def test_cancelled_delay_constructs_no_simulator_or_keystrokes():
    for table in (False, True):
        target = app()
        target._cancel_event.wait = Mock(return_value=True)
        with patch('src.orchestrator.KeystrokeSimulator') as simulator:
            if table:
                target._table_fill_pipeline([ClipboardContent('cell')])
            else:
                target._typing_pipeline(ClipboardContent('cell'))
            simulator.assert_not_called()
            target._execute_plan.assert_not_called()
