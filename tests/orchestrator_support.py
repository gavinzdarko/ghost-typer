"""Headless imports for orchestrator regressions; no keyboard or GUI access."""
from unittest.mock import Mock
import sys

# Replace only unavailable/UI dependencies, retaining loaded application modules.
_stubs = {name: Mock() for name in ("tkinter", "tkinter.ttk", "tkinter.messagebox", "src.keystroke_simulator")}
_originals = {name: sys.modules.get(name) for name in _stubs}
sys.modules.update(_stubs)
from src.orchestrator import Orchestrator
for _name, _module in _originals.items():
    if _module is None:
        sys.modules.pop(_name, None)
    else:
        sys.modules[_name] = _module
