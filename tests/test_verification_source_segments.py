from unittest.mock import Mock, patch

from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.models import TextSegment, TypeText, TypingPlan


def test_verification_preserves_adjacency_across_formatting_segments():
    with patch("src.orchestrator.load_settings_dict", return_value={"ai_enabled": False, "start_delay": 0}):
        target = Orchestrator()
    target.notification_service = Mock()
    segments = [TextSegment("un"), TextSegment("break", formatting={"bold": True}), TextSegment("able"),
                TextSegment("\n\n"), TextSegment("Next.")]
    target.text_parser.parse = Mock(return_value=segments)
    target.fallback_planner.plan = Mock(return_value=TypingPlan(actions=[TypeText(text="unbreakable\n\nNext.")]))
    target._execute_plan = Mock()
    target.visual_verifier = Mock(enabled=True)
    with patch("src.orchestrator.KeystrokeSimulator", return_value=Mock(is_active=True)):
        target._typing_pipeline(ClipboardContent("source"))
    target.visual_verifier.verify.assert_called_once_with("unbreakable\n\nNext.", cancel_event=target._cancel_event)
