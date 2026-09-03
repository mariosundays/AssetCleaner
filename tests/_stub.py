"""
Shared stubs so the logic can be tested without Houdini or Qt.

Import this first, before asset_cleaner, in every suite.
"""
import os
import sys
import types

# --- stub hou ---
hou = types.ModuleType("hou")
hou.getenv = lambda k: os.environ.get(k)


class _PT:
    pass


hou.StringParmTemplate = _PT
hou.stringParmType = types.SimpleNamespace(FileReference="fileref")
hou.OperationFailed = Exception
hou.PermissionError = Exception
hou.node = lambda p: None
hou.hipFile = types.SimpleNamespace(path=lambda: "x.hip")
hou.ui = types.SimpleNamespace()
hou.undos = types.SimpleNamespace()
hou.severityType = types.SimpleNamespace(Warning=1, Message=0)
hou.qt = types.SimpleNamespace(mainWindow=lambda: None)
sys.modules["hou"] = hou


# --- stub PySide6 ---
class _Any:
    """Stub that is usable as a value AND as a base class."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return _Any()

    def __call__(self, *a, **k):
        return _Any()

    def __mro_entries__(self, bases):
        return (_Base,)


class _Base:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, n):
        return _Any()


for name in ["PySide6", "PySide6.QtCore", "PySide6.QtGui",
             "PySide6.QtWidgets"]:
    sys.modules[name] = types.ModuleType(name)

sys.modules["PySide6.QtCore"].Qt = _Any()
for mod in ["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"]:
    sys.modules[mod].__class__ = type(
        "M", (types.ModuleType,), {"__getattr__": lambda s, n: _Any()})
sys.modules["PySide6"].QtCore = sys.modules["PySide6.QtCore"]
sys.modules["PySide6"].QtGui = sys.modules["PySide6.QtGui"]
sys.modules["PySide6"].QtWidgets = sys.modules["PySide6.QtWidgets"]

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "python"))


# --- tiny assertion helpers, shared by every suite ---
_checks = [0]


def check(condition, label):
    _checks[0] += 1
    if not condition:
        raise AssertionError(label)


def done(suite):
    print("{}: {} checks passed".format(suite, _checks[0]))
