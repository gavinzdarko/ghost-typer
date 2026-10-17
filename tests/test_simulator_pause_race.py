import threading
from unittest.mock import Mock, patch

from src.keystroke_simulator import KeystrokeSimulator


def simulator():
    with patch("src.keystroke_simulator.Controller"):
        return KeystrokeSimulator()


def test_pause_between_state_check_and_event_blocks_key_until_resume():
    sim = simulator()
    checked, proceed = threading.Event(), threading.Event()
    original = sim._check_state
    first = [True]
    def check():
        result = original()
        if first[0]:
            first[0] = False
            checked.set()
            assert proceed.wait(2)
        return result
    sim._check_state = check
    worker = threading.Thread(target=sim.type_char, args=("x",))
    worker.start()
    try:
        assert checked.wait(2)
        sim.pause()
        proceed.set()
        worker.join(.1)
        assert worker.is_alive()
        sim._controller.type.assert_not_called()
        sim.resume()
        worker.join(2)
        assert not worker.is_alive()
        sim._controller.type.assert_called_once_with("x")
    finally:
        proceed.set()
        sim.stop()
        sim.resume()
        worker.join(2)


def test_pause_waits_for_inflight_event_before_returning():
    sim = simulator()
    inflight, finish, paused = (threading.Event() for _ in range(3))
    def emit(_char):
        inflight.set()
        assert finish.wait(2)
    sim._controller.type.side_effect = emit
    worker = threading.Thread(target=sim.type_char, args=("x",))
    worker.start()
    assert inflight.wait(2)
    pauser = threading.Thread(target=lambda: (sim.pause(), paused.set()))
    pauser.start()
    try:
        assert not paused.wait(.1)
        finish.set()
        assert paused.wait(2)
    finally:
        finish.set()
        worker.join(2)
        pauser.join(2)
    assert sim.is_paused
