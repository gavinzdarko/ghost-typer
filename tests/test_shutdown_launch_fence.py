from unittest.mock import Mock, patch

from test_cancel_ownership import app


def test_shutdown_rejects_a_callback_between_cancel_and_clipboard_stop():
    target = app()
    launches = []
    target.cancel = Mock(side_effect=lambda **kwargs: launches.append(
        target._launch_pipeline(Mock(), (), "late-callback")))
    target.clipboard_monitor.stop = Mock()
    target.stop()
    assert launches == [False]
    assert target._typing_thread is None
    assert not target.is_enabled
    target.clipboard_monitor.stop.assert_called_once()


def test_enable_after_a_stop_explicitly_reopens_launches():
    target = app()
    target.stop()
    assert target._sessions_disabled
    target.enable()
    assert not target._sessions_disabled
    assert target.is_enabled
