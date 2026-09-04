# Tests

Logic tests for the parts that do not need Houdini. `hou` and PySide are
stubbed by `_stub.py`, so these run under any Python 3 with no dependencies:

    python tests/run_all.py

| Suite | Covers |
|---|---|
| `test_logic.py` | Extensions, sequences, backup/version detection, classification |
| `test_hipscan.py` | Reading asset paths out of a `.hip` without opening it |
| `test_move.py` | Move and restore end to end, on real temp files |
| `test_scan.py` | The whole scan, including the other-scene downgrade |
| `test_frames.py` | Compound extensions (.bgeo.sc) and the sequence safety net |
| `test_output.py` | Render/comp detection, by ROP path and by folder name |
| `test_group.py` | Collapsing frame sequences into one row each |
| `test_group_move.py` | Moving a sequence row moves every frame in it |
| `test_ui.py` | Column ids, signal targets, sortable cells |

`test_move.py`, `test_hipscan.py` and `test_scan.py` write to a temp directory
and clean up after themselves.

The most important single test is in `test_scan.py`: a file referenced only by
a *sibling* scene must be listed but never ticked. That is the property that
keeps the tool from eating another shot's textures.

Not covered: the Qt widgets themselves and the real Houdini scene walk, both
of which need a live Houdini session.
