import ast
import queue
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def drain():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/menu_bar_app.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GhostTyperApp")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_process_gui_queue")
    scope = {"queue": queue, "logger": Mock()}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "<queue>", "exec"), scope)
    return scope["_process_gui_queue"]


def test_continuous_producers_yield_to_the_appkit_loop():
    target = SimpleNamespace(_shutting_down=False, _gui_queue=queue.Queue())
    calls = []
    def producer():
        calls.append(1)
        if len(calls) < 1000:
            target._gui_queue.put(producer)
    target._gui_queue.put(producer)
    drain()(target, None)
    assert 0 < len(calls) < 1000
    assert target._gui_queue.qsize() == 1


def test_shutdown_during_callback_stops_already_queued_gui_mutations():
    target = SimpleNamespace(_shutting_down=False, _gui_queue=queue.Queue())
    late = Mock()
    target._gui_queue.put(lambda: setattr(target, "_shutting_down", True))
    target._gui_queue.put(late)
    drain()(target, None)
    late.assert_not_called()


def test_failed_callback_does_not_discard_following_work():
    target = SimpleNamespace(_shutting_down=False, _gui_queue=queue.Queue())
    target._gui_queue.put(Mock(side_effect=RuntimeError("failed")))
    healthy = Mock()
    target._gui_queue.put(healthy)
    drain()(target, None)
    healthy.assert_called_once()
