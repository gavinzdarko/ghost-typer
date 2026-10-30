import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import queue
import threading


def test_listener_can_deliver_toggle_immediately_during_startup():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src/menu_bar_app.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GhostTyperApp")
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in
               {"__init__", "_run_on_main", "_hotkey_toggle_enabled", "_toggle"}]
    fake_rumps = Mock()
    class AppBase:
        def __init__(self, **kwargs):
            pass
    fake_rumps.App = AppBase
    base_cls = ast.ClassDef(name="FakeApp", bases=[ast.Attribute(value=ast.Name(id="rumps", ctx=ast.Load()), attr="App", ctx=ast.Load())],
                           keywords=[], body=methods, decorator_list=[])
    icons = {n.targets[0].id: "icon" for n in tree.body if isinstance(n, ast.Assign)
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id.startswith("ICON_")}
    listener = Mock()
    scope = {"rumps": fake_rumps, "Orchestrator": object, "queue": queue, "threading": threading,
             "HotkeyListener": Mock(return_value=listener), "ProgressOverlay": Mock(),
             "_MenuDelegate": Mock(), "load_settings_dict": Mock(return_value={}), **icons}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[base_cls], type_ignores=[])), "<startup>", "exec"), scope)
    FakeApp = scope["FakeApp"]
    for name in ("_on_state_change", "_on_progress", "_wire_menu_delegate", "_build_settings_menu", "_process_gui_queue",
                 "_hotkey_toggle_pause", "_hotkey_emergency_stop", "_hotkey_paste", "_pause_resume", "_cancel",
                 "_toggle_table_fill", "_run_table_fill", "_on_table_queue_change", "_quit"):
        setattr(FakeApp, name, Mock())
    def ready_callback():
        instance = scope["HotkeyListener"].call_args.kwargs["on_toggle_enabled"].__self__
        instance._hotkey_toggle_enabled()
        assert instance._gui_queue.qsize() == 1
        assert instance._toggle_item is not None
    listener.start.side_effect = ready_callback
    orch = Mock(is_enabled=False)
    target = FakeApp(orch)
    orch.enable.assert_not_called()
    target._gui_queue.get_nowait()()
    orch.enable.assert_called_once()
    assert target._animation_stop.is_set()
