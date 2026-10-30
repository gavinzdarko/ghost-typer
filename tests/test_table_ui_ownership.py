"""Queue displays follow live work even when producer notifications reorder."""
import ast
from pathlib import Path
from threading import Event, RLock, Thread
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from orchestrator_support import Orchestrator
from src.clipboard_monitor import ClipboardContent
from src.orchestrator import OrchestratorState


def queue_method():
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'GhostTyperApp')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == '_on_table_queue_change')
    scope = {'OrchestratorState': OrchestratorState}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<table queue UI>', 'exec'), scope)
    return scope['_on_table_queue_change']


def target():
    orch = Orchestrator.__new__(Orchestrator)
    orch._table_queue_lock = RLock()
    orch._table_queue = []
    orch._table_fill_mode = True
    orch.clipboard_monitor = SimpleNamespace(_immediate_mode=True, enabled=True)
    orch._state = OrchestratorState.IDLE
    orch._state_revision = 0
    orch._state_lock = RLock()
    orch._session_lock = RLock()
    orch._typing_thread = None
    orch.on_state_change = None
    queued = []
    app = SimpleNamespace(orchestrator=orch, _table_run_item=SimpleNamespace(title='Run Table (0 items)'),
        _status_item=SimpleNamespace(title='Status: Idle'), _table_fill_item=SimpleNamespace(state=1),
        _run_on_main=queued.append)
    orch.on_table_queue_change = lambda count: queue_method()(app, count)
    return app, queued


def test_real_producer_notification_delayed_across_mode_disable_uses_empty_queue():
    app, queued = target()
    entered, release = Event(), Event()
    notify = app.orchestrator.on_table_queue_change
    def delayed(count):
        if count:
            entered.set()
            assert release.wait(2)
        notify(count)
    app.orchestrator.on_table_queue_change = delayed
    producer = Thread(target=app.orchestrator._add_to_table_queue,
                      args=(ClipboardContent('one\ntwo\nthree'),))
    producer.start()
    try:
        assert entered.wait(2)
        app.orchestrator.disable_table_fill()
    finally:
        release.set()
        producer.join(2)
    assert not producer.is_alive()
    for callback in queued:
        callback()
    assert app.orchestrator.table_queue_count() == 0
    assert app._table_run_item.title == 'Run Table (0 items)'
    assert app._table_fill_item.state == 0
    assert app._status_item.title == 'Status: Idle'


def test_delivery_after_actual_queued_run_preserves_planning_status():
    app, queued = target()
    app.orchestrator._add_to_table_queue(ClipboardContent('one\ntwo'))
    def launch(*args):
        app.orchestrator.state = OrchestratorState.PLANNING
        return True
    app.orchestrator._launch_pipeline = Mock(side_effect=launch)
    assert app.orchestrator.run_table_fill()
    app._status_item.title = 'Status: AI Planning...'
    for callback in queued:
        callback()
    assert app._table_run_item.title == 'Run Table (0 items)'
    assert app._table_fill_item.state == 0
    assert app._status_item.title == 'Status: AI Planning...'


@pytest.mark.parametrize('state', [OrchestratorState.PLANNING, OrchestratorState.TYPING,
                                   OrchestratorState.PAUSED, OrchestratorState.VERIFYING])
def test_queued_cells_do_not_overwrite_active_session_status(state):
    app, queued = target()
    app.orchestrator._add_to_table_queue(ClipboardContent('retained work'))
    app.orchestrator.state = state
    app._status_item.title = 'active session'
    for callback in queued:
        callback()
    assert app._table_run_item.title == 'Run Table (1 item)'
    assert app._status_item.title == 'active session'


def test_retained_queue_while_off_does_not_claim_active_table_mode():
    app, queued = target()
    app.orchestrator._add_to_table_queue(ClipboardContent('retained work'))
    app.orchestrator.clipboard_monitor.enabled = False
    app._status_item.title = 'Status: Off'
    for callback in queued:
        callback()
    assert app._table_run_item.title == 'Run Table (1 item)'
    assert app._status_item.title == 'Status: Off'


def test_current_idle_queue_and_mode_are_displayed():
    app, queued = target()
    app.orchestrator._add_to_table_queue(ClipboardContent('one\ntwo'))
    for callback in queued:
        callback()
    assert app._table_run_item.title == 'Run Table (2 items)'
    assert app._table_fill_item.state == 1
    assert app._status_item.title == 'Table Fill: 2 items queued'
