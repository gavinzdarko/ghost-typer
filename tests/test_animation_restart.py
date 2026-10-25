"""A stopped animation worker may still be alive when typing resumes."""
import ast
from pathlib import Path
from types import SimpleNamespace
import threading
from unittest.mock import Mock


def target():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in {'_start_animation', '_stop_animation', '_animate'}]
    workers = []
    def worker(**kwargs):
        thread = Mock(**{'is_alive.return_value': True})
        workers.append((thread, kwargs))
        return thread
    scope = {'threading': SimpleNamespace(Event=threading.Event, Thread=worker),
             'ICON_TYPING': 'frame1', 'ICON_TYPING2': 'frame2', 'ICON_TYPING3': 'frame3'}
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<animation>', 'exec'), scope)
    app = SimpleNamespace(_animation_thread=None, _animation_stop=threading.Event(), icon='idle')
    app._animate = lambda stop: scope['_animate'](app, stop)
    app.start = lambda: scope['_start_animation'](app)
    app.stop = lambda: scope['_stop_animation'](app)
    return app, workers


def test_restart_replaces_stopped_worker_even_while_it_is_still_alive():
    app, workers = target()
    app.start()
    old_worker, old_args = workers[0]
    old_stop = old_args['args'][0]
    app.stop()
    app.start()
    assert old_stop.is_set()
    assert len(workers) == 2
    assert app._animation_thread is not old_worker
    assert not app._animation_stop.is_set()
    assert workers[1][1]['args'] == (app._animation_stop,)
    workers[1][0].start.assert_called_once()


def test_repeated_start_reuses_active_worker():
    app, workers = target()
    app.start()
    app.start()
    assert len(workers) == 1


def test_frame_from_stopped_worker_stays_inactive_after_restart():
    app, workers = target()
    app.start()
    old_stop = app._animation_stop
    queued = []
    def enqueue(key, fn):
        queued.append(fn)
        app.stop()
    app._queue_gui_update = enqueue
    workers[0][1]['target'](old_stop)
    app.start()
    queued[0]()
    assert app.icon == 'idle'
    assert old_stop.is_set()
    assert not app._animation_stop.is_set()
