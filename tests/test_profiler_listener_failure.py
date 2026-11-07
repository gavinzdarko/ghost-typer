from unittest.mock import Mock

import pytest

import typing_profiler as module


def listener_recorder(monkeypatch, *, alive=False, error=None):
    listener = Mock()
    listener.is_alive.return_value = alive
    listener.join.side_effect = error
    monkeypatch.setattr(module.keyboard, 'Listener', Mock(return_value=listener))
    recorder = module.TypingRecorder()
    recorder.start()
    return recorder, listener


@pytest.mark.parametrize('error', [None, RuntimeError('event tap failed')])
def test_dead_listener_reports_failure_instead_of_waiting_for_escape(monkeypatch, error):
    recorder, listener = listener_recorder(monkeypatch, error=error)
    with pytest.raises(RuntimeError, match='keyboard listener'):
        _ = recorder.is_done
    listener.join.assert_called_once_with(timeout=0)


def test_live_listener_and_escape_still_work(monkeypatch):
    recorder, listener = listener_recorder(monkeypatch, alive=True)
    assert not recorder.is_done
    recorder._on_press(module.keyboard.Key.esc)
    listener.is_alive.return_value = False
    assert recorder.is_done
    listener.join.assert_not_called()


@pytest.mark.parametrize('fail_on_start', [False, True])
def test_cli_listener_failures_stop_recording_without_export(monkeypatch, tmp_path, capsys, fail_on_start):
    listener = Mock()
    listener.is_alive.return_value = False
    listener.join.side_effect = RuntimeError('event tap failed')
    if fail_on_start:
        listener.start.side_effect = RuntimeError('startup failed')
    monkeypatch.setattr(module.keyboard, 'Listener', Mock(return_value=listener))
    output = tmp_path / 'profile.json'
    monkeypatch.setattr(module.sys, 'argv', ['typing_profiler.py', '--freeform', '-o', str(output)])
    # The liveness check must fail on the first poll, before the wait loop.
    monkeypatch.setattr(module.time, 'sleep', Mock(side_effect=AssertionError('hung waiting for ESC')))
    with pytest.raises(SystemExit) as exit_info:
        module.main()
    assert exit_info.value.code == 1
    listener.stop.assert_called_once()
    assert not output.exists()
    assert not output.with_suffix('.settings.json').exists()
    assert 'Accessibility' in capsys.readouterr().out
