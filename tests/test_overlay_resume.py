from unittest.mock import Mock, patch
from src.progress_overlay import ProgressOverlay


def overlay():
    view = ProgressOverlay()
    view._ensure_window = Mock(return_value=True)
    view._window = Mock()
    view._bar_view = Mock()
    view._label = Mock()
    view._start_tick_timer = Mock()
    view._stop_tick_timer = Mock()
    return view


def test_resume_retains_progress_and_excludes_manual_pause_from_eta():
    view = overlay()
    now = [100.0]
    with patch('src.progress_overlay.time.time', side_effect=lambda: now[0]):
        view.show()
        view.update(0, 100, start_time=100, estimated_total=200)
        now[0] = 120
        view.update(20, 100, start_time=100)
        estimate = view._locked_total_time
        before = view._label.setStringValue_.call_args.args[0]
        view.pause()
        now[0] = 1120
        view.show()
        assert view._pct == 0.2
        assert view._start_time == 100
        assert view._locked_total_time == estimate
        assert view._active_elapsed() == 20
        assert view._label.setStringValue_.call_args.args[0] == before
        now[0] = 1130
        view.update(30, 100, start_time=100)
        assert view._active_elapsed() == 30
        assert view._locked_total_time == estimate * .8 + 100 * .2


def test_cancelled_pause_does_not_carry_into_next_session():
    view = overlay()
    with patch('src.progress_overlay.time.time', return_value=100):
        view.show()
        view.update(50, 100, start_time=100, estimated_total=200)
        view.pause()
        view.hide()
        view.show()
    assert view._pct == 0
    assert view._start_time == 0
    assert view._locked_total_time == 0
    assert view._paused_seconds == 0
