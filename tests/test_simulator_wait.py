from unittest.mock import patch

from src.keystroke_simulator import KeystrokeSimulator


def test_pause_time_does_not_consume_planned_wait(monkeypatch):
    with patch('src.keystroke_simulator.Controller'):
        sim = KeystrokeSimulator()
    clock = [0.0]
    waits = []
    checks = [0]

    def check():
        checks[0] += 1
        if checks[0] == 2:
            clock[0] += 100  # manual pause, separate from the planned delay
        return True

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(sim, '_check_state', check)
    monkeypatch.setattr('src.keystroke_simulator.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('src.keystroke_simulator.time.time', lambda: -1000000)
    monkeypatch.setattr('src.keystroke_simulator.time.sleep', sleep)
    sim.wait(0.2)
    assert abs(sum(waits) - 0.2) < 1e-8
    assert max(waits) <= 0.05


def test_stopped_wait_exits_without_sleeping(monkeypatch):
    with patch('src.keystroke_simulator.Controller'):
        sim = KeystrokeSimulator()
    sim.stop()
    with patch('src.keystroke_simulator.time.sleep') as sleep:
        sim.wait(10)
    sleep.assert_not_called()
