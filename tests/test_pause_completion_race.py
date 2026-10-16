import threading
from unittest.mock import Mock
from orchestrator_support import Orchestrator
from src.orchestrator import OrchestratorState


def app(state):
    instance = Orchestrator.__new__(Orchestrator)
    instance._state = state
    instance._state_revision = 0
    instance._state_lock = threading.Lock()
    instance._session_lock = threading.RLock()
    instance.on_state_change = Mock()
    instance.notification_service = Mock()
    instance._simulator = Mock()
    return instance


def test_completion_during_pause_cannot_leave_idle_session_paused():
    instance = app(OrchestratorState.TYPING)
    instance._simulator.pause.side_effect = lambda: setattr(instance, 'state', OrchestratorState.IDLE)
    instance.pause()
    assert instance.state == OrchestratorState.IDLE
    instance.notification_service.notify_paused.assert_not_called()
    instance._simulator.resume.assert_called_once()


def test_completion_during_resume_cannot_leave_idle_session_typing():
    instance = app(OrchestratorState.PAUSED)
    instance._simulator.resume.side_effect = lambda: setattr(instance, 'state', OrchestratorState.IDLE)
    instance.resume()
    assert instance.state == OrchestratorState.IDLE
    instance.notification_service.notify_resumed.assert_not_called()


def test_normal_pause_resume_and_missing_simulator():
    instance = app(OrchestratorState.TYPING)
    instance.pause()
    assert instance.state == OrchestratorState.PAUSED
    instance.resume()
    assert instance.state == OrchestratorState.TYPING
    instance._simulator = None
    instance.pause()
    assert instance.state == OrchestratorState.TYPING


def menu(instance):
    # Run the application method without importing AppKit or sending input.
    import ast
    from pathlib import Path
    from types import SimpleNamespace

    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/menu_bar_app.py").read_text())
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "GhostTyperApp")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "_on_state_change")
    method.returns = None
    for argument in method.args.args:
        argument.annotation = None
    scope = {"OrchestratorState": OrchestratorState,
             **{name: name for name in ("ICON_IDLE", "ICON_OFF", "ICON_PLANNING", "ICON_VERIFYING", "ICON_PAUSED")}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "<menu-method>", "exec"), scope)
    queued = []
    view = SimpleNamespace(
        orchestrator=instance, _state_effects_lock=threading.Lock(), _state_effects_revision=-1,
        _hotkey_listener=Mock(), _progress_overlay=Mock(), _status_item=Mock(),
        _pause_item=Mock(), _cancel_item=Mock(), _stop_animation=Mock(),
        _start_animation=Mock(), _pause_resume=Mock(), _cancel=Mock(),
        _run_on_main=queued.append)
    return view, queued, lambda state: scope["_on_state_change"](view, state)


def test_late_resume_callback_cannot_revive_completed_menu_or_suppress_paste():
    instance = app(OrchestratorState.PAUSED)
    instance.clipboard_monitor = Mock(enabled=True)
    view, queued, changed = menu(instance)
    started, release = threading.Event(), threading.Event()
    def delayed(state):
        if state == OrchestratorState.TYPING:
            started.set()
            assert release.wait(2)
        changed(state)
    instance.on_state_change = delayed
    worker = threading.Thread(target=instance.resume)
    try:
        worker.start()
        assert started.wait(1)
        instance.state = OrchestratorState.IDLE
        release.set()
        worker.join(1)
        assert not worker.is_alive()
        for update in queued:
            update()
        assert view._status_item.title == "Status: Idle"
        view._hotkey_listener.unsuppress.assert_called_once()
        view._hotkey_listener.suppress.assert_not_called()
        view._progress_overlay.show.assert_not_called()
    finally:
        release.set()
        worker.join(2)


def test_queued_state_update_from_previous_session_cannot_reset_new_overlay():
    instance = app(OrchestratorState.IDLE)
    view, queued, changed = menu(instance)
    instance.on_state_change = changed
    instance.state = OrchestratorState.TYPING
    old_update = queued.pop()
    instance.state = OrchestratorState.IDLE
    instance.state = OrchestratorState.TYPING
    for update in queued:
        update()
    old_update()
    assert view._status_item.title == "Status: Typing..."
    view._progress_overlay.show.assert_called_once()


def test_hotkey_effects_remain_ordered_when_completion_races_suppression():
    instance = app(OrchestratorState.PAUSED)
    instance.clipboard_monitor = Mock(enabled=True)
    view, queued, changed = menu(instance)
    suppressing, release, completing = threading.Event(), threading.Event(), threading.Event()
    suppressed = [False]
    def suppress():
        suppressing.set()
        assert release.wait(2)
        suppressed[0] = True
    def unsuppress():
        suppressed[0] = False
    view._hotkey_listener.suppress.side_effect = suppress
    view._hotkey_listener.unsuppress.side_effect = unsuppress
    def notify(state):
        if state == OrchestratorState.IDLE:
            completing.set()
        changed(state)
    instance.on_state_change = notify
    resume = threading.Thread(target=instance.resume)
    complete = threading.Thread(target=lambda: setattr(instance, "state", OrchestratorState.IDLE))
    try:
        resume.start()
        assert suppressing.wait(1)
        complete.start()
        assert completing.wait(1)
        assert instance.state == OrchestratorState.IDLE
        release.set()
        resume.join(1)
        complete.join(1)
        assert not resume.is_alive() and not complete.is_alive()
        assert not suppressed[0]
        for update in queued:
            update()
        assert view._status_item.title == "Status: Idle"
    finally:
        release.set()
        resume.join(2)
        if complete.ident is not None:
            complete.join(2)
