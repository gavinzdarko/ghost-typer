"""A blocked native menu must not accumulate a history of progress frames."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import threading


def target():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_queue_gui_update')
    scope = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<gui>', 'exec'), scope)
    queued = []
    app = SimpleNamespace(_gui_update_lock=threading.Lock(), _gui_updates={},
                          _shutting_down=False, _run_on_main=queued.append)
    app.update = lambda key, fn: scope['_queue_gui_update'](app, key, fn)
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
