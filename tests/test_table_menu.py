import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

def test_menu_keeps_queue_count_when_table_start_is_rejected():
    # Execute only the actual caller method to avoid importing native AppKit/rumps.
    tree = ast.parse((Path(__file__).resolve().parents[1] / 'src/menu_bar_app.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GhostTyperApp')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_run_table_fill')
    method.returns = None
    for arg in method.args.args:
        arg.annotation = None
    scope = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<menu-method>', 'exec'), scope)
    app = SimpleNamespace(orchestrator=Mock(), _table_fill_item=SimpleNamespace(state=1),
        _table_run_item=SimpleNamespace(title='Run Table (2 items)'))
    app.orchestrator.table_queue_count.return_value = 2
    app.orchestrator.run_table_fill.return_value = False
    scope['_run_table_fill'](app, None)
    assert app._table_fill_item.state == 1
    assert app._table_run_item.title == 'Run Table (2 items)'
