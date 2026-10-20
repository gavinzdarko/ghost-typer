"""A blocked native menu must not accumulate a history of progress frames."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import threading


def target():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in ('_queue_gui_update', '_on_progress')]
    scope = {'OrchestratorState': SimpleNamespace(TYPING='typing')}
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<gui>', 'exec'), scope)
    queued = []
    app = SimpleNamespace(_gui_update_lock=threading.Lock(), _gui_updates={},
                          _shutting_down=False, _run_on_main=queued.append)
    app.update = lambda key, fn: scope['_queue_gui_update'](app, key, fn)
    app._queue_gui_update = app.update
    app.progress = lambda *args: scope['_on_progress'](app, *args)
    return app, queued


def test_thousands_of_frames_keep_only_latest_per_kind():
    app, queued = target()
    delivered = []
    for i in range(10_000):
        app.update('progress', lambda value=i: delivered.append(('progress', value)))
        app.update('animation', lambda value=i: delivered.append(('animation', value)))
    assert len(queued) == 2
    for fn in queued:
        fn()
    assert delivered == [('progress', 9999), ('animation', 9999)]
    assert not app._gui_updates


def test_previous_session_delivery_cannot_move_new_progress_before_initial_eta():
    app, queued = target()
    app.orchestrator = SimpleNamespace(state_snapshot=('typing', 1))
    app._status_item = SimpleNamespace(title='')
    app._progress_overlay = Mock()
    app.progress(10, 100, 1)
    app.orchestrator.state_snapshot = ('typing', 3)
    app.progress(0, 100, 3, 20)
    app.progress(50, 100, 3)
    for fn in queued:
        fn()
    assert [call.args[:2] for call in app._progress_overlay.update.call_args_list] == [(0, 100), (50, 100)]
    assert '50%' in app._status_item.title


def test_update_during_delivery_is_scheduled_and_shutdown_rejects_new_work():
    app, queued = target()
    last = Mock()
    app.update('progress', lambda: app.update('progress', last))
    queued.pop(0)()
    assert len(queued) == 1
    queued.pop(0)()
    last.assert_called_once()
    app._shutting_down = True
    app.update('progress', Mock())
    assert not queued
    assert not app._gui_updates
