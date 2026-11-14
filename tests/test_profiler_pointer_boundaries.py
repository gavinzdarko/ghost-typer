"""Exercise native pointer capture without creating any OS event taps."""
from threading import Event, Thread
from unittest.mock import Mock, patch

import pytest
from pynput import mouse

import typing_profiler as module


def listeners(monkeypatch):
    keyboard_listener = Mock()
    pointer_listener = Mock()
    keyboard_listener.is_alive.return_value = True
    pointer_listener.is_alive.return_value = True
    monkeypatch.setattr(module.keyboard, 'Listener', Mock(return_value=keyboard_listener))
    monkeypatch.setattr(mouse, 'Listener', Mock(return_value=pointer_listener))
    return keyboard_listener, pointer_listener


@pytest.mark.parametrize('button', [mouse.Button.left, mouse.Button.right])
def test_pointer_press_breaks_digraph_pause_and_correction_runs(monkeypatch, button):
    listeners(monkeypatch)
    recorder = module.TypingRecorder()
    recorder.start()
    callback = mouse.Listener.call_args.kwargs['on_click']
    with patch.object(module.time, 'monotonic', side_effect=[1, 2, 3, 4]):
        recorder._on_press(module.keyboard.KeyCode.from_char('a'))
        callback(20, 30, button, True)
        recorder._on_press(module.keyboard.KeyCode.from_char('b'))
        recorder._on_press(module.keyboard.Key.backspace)
        callback(50, 60, button, True)
        recorder._on_press(module.keyboard.Key.backspace)
    analyzer = module.TypingAnalyzer(recorder.events)
    analyzer._compute_intervals()
    analyzer._detect_pauses()
    analyzer._detect_corrections()
    assert analyzer.intervals == []
    assert analyzer.pauses == []
    assert [correction.chars_deleted for correction in analyzer.corrections] == [1, 1]
    assert recorder.events[0].run_id != recorder.events[1].run_id
    recorder.stop()


def test_mouse_release_and_movement_do_not_interrupt_typing(monkeypatch):
    listeners(monkeypatch)
    recorder = module.TypingRecorder()
    recorder.start()
    callbacks = mouse.Listener.call_args.kwargs
    assert callbacks.get('on_move') is None
    recorder._on_press(module.keyboard.KeyCode.from_char('a'))
    callbacks['on_click'](1, 2, mouse.Button.left, False)
    recorder._on_press(module.keyboard.KeyCode.from_char('b'))
    assert recorder.events[0].run_id == recorder.events[1].run_id
    recorder.stop()


@pytest.mark.parametrize('failed', ['keyboard', 'pointer'])
def test_startup_failure_stops_both_owned_listeners(monkeypatch, failed):
    keyboard_listener, pointer_listener = listeners(monkeypatch)
    (keyboard_listener if failed == 'keyboard' else pointer_listener).start.side_effect = RuntimeError('tap failed')
    recorder = module.TypingRecorder()
    with pytest.raises(RuntimeError, match='tap failed'):
        recorder.start()
    keyboard_listener.stop.assert_called_once()
    pointer_listener.stop.assert_called_once()
    recorder.stop()  # CLI's finally cleanup is idempotent.
    keyboard_listener.stop.assert_called_once()
    pointer_listener.stop.assert_called_once()


def test_dead_pointer_listener_fails_instead_of_exporting_contaminated_data(monkeypatch):
    _, pointer_listener = listeners(monkeypatch)
    recorder = module.TypingRecorder()
    recorder.start()
    pointer_listener.is_alive.return_value = False
    pointer_listener.join.side_effect = RuntimeError('pointer tap failed')
    with pytest.raises(RuntimeError, match='pointer listener'):
        _ = recorder.is_done
    recorder.stop()


def test_stop_cleans_up_pointer_even_when_keyboard_stop_fails(monkeypatch):
    keyboard_listener, pointer_listener = listeners(monkeypatch)
    recorder = module.TypingRecorder()
    recorder.start()
    keyboard_listener.stop.side_effect = RuntimeError('stop failed')
    with pytest.raises(RuntimeError, match='stop failed'):
        recorder.stop()
    pointer_listener.stop.assert_called_once()


def test_callback_records_timestamp_and_event_in_one_locked_transaction(monkeypatch):
    listeners(monkeypatch)
    recorder = module.TypingRecorder()
    recorder.start()
    callback = mouse.Listener.call_args.kwargs['on_click']
    entered = Event()
    release = Event()
    def timestamp():
        assert recorder._record_lock.locked()
        entered.set()
        assert release.wait(1)
        return 1
    monkeypatch.setattr(module.time, 'monotonic', timestamp)
    key_worker = Thread(target=recorder._on_press, args=(module.keyboard.KeyCode.from_char('a'),))
    click_worker = Thread(target=callback, args=(1, 2, mouse.Button.left, True))
    key_worker.start()
    assert entered.wait(1)
    click_worker.start()
    release.set()
    key_worker.join(1)
    click_worker.join(1)
    assert not key_worker.is_alive() and not click_worker.is_alive()
    recorder._on_press(module.keyboard.KeyCode.from_char('b'))
    assert [event.run_id for event in recorder.events] == [0, 1]
    recorder.stop()


def test_pointer_constructor_failure_cleans_up_keyboard_listener(monkeypatch):
    keyboard_listener, _ = listeners(monkeypatch)
    mouse.Listener.side_effect = RuntimeError('pointer setup failed')
    recorder = module.TypingRecorder()
    with pytest.raises(RuntimeError, match='pointer setup failed'):
        recorder.start()
    keyboard_listener.stop.assert_called_once()
    assert recorder.is_done


def test_callbacks_after_stop_cannot_mutate_recording(monkeypatch):
    keyboard_listener, pointer_listener = listeners(monkeypatch)
    recorder = module.TypingRecorder()
    recorder.start()
    callback = mouse.Listener.call_args.kwargs['on_click']
    recorder._on_press(module.keyboard.KeyCode.from_char('a'))
    recorder.stop()
    callback(1, 2, mouse.Button.left, True)
    recorder._on_press(module.keyboard.KeyCode.from_char('b'))
    recorder._on_release(module.keyboard.Key.cmd)
    assert [event.char for event in recorder.events] == ['a']
    keyboard_listener.stop.assert_called_once()
    pointer_listener.stop.assert_called_once()


@pytest.mark.parametrize('which', ['keyboard', 'pointer'])
def test_escape_wins_listener_liveness_race(monkeypatch, which):
    keyboard_listener, pointer_listener = listeners(monkeypatch)
    recorder = module.TypingRecorder()
    recorder.start()
    listener = keyboard_listener if which == 'keyboard' else pointer_listener
    def finish_while_checking_liveness():
        recorder._on_press(module.keyboard.Key.esc)
        return False
    listener.is_alive.side_effect = finish_while_checking_liveness
    assert recorder.is_done
    listener.join.assert_not_called()
    recorder.stop()
