"""
Frame parsing, and the safety net that stops a referenced sequence being
reported as never referenced.

Both bugs these cover were found on a real project:

  - .bgeo.sc caches did not group and were not protected, because the frame
    regex assumed a single-dot extension.
  - A sequence whose glob resolved nothing left every frame looking unused.
"""
import os
import shutil
import tempfile
import types

import _stub
from _stub import check, done

import asset_cleaner as ac


# -- compound extensions ---------------------------------------------------
# .bgeo.sc is THE Houdini cache format. Getting this wrong meant every cache
# frame was offered up for deletion.

for name, stem, num, ext in (
        ("cache.0001.bgeo.sc", "cache.", 1, ".bgeo.sc"),
        ("cache.0001.bgeo", "cache.", 1, ".bgeo"),
        ("pyro.0100.vdb.sc", "pyro.", 100, ".vdb.sc"),
        ("fx_v01.0248.bgeo.sc", "fx_v01.", 248, ".bgeo.sc"),
        ("beauty.0001.exr", "beauty.", 1, ".exr"),
        ("wall_0007.tif", "wall_", 7, ".tif"),
):
    parts = ac.split_frame("c:/p/geo/" + name)
    check(parts is not None, "split_frame parses " + name)
    folder, got_stem, got_num, _width, got_ext = parts
    check(got_stem == stem, "stem of " + name)
    check(got_num == num, "frame number of " + name)
    check(got_ext == ext, "extension of " + name)

check(ac.frame_stem("c:/p/geo/cache.0001.bgeo.sc") == "c:/p/geo/cache.",
      "compound extension yields a frame stem")
check(ac.frame_number("c:/p/geo/cache.0042.bgeo.sc") == 42,
      "compound extension yields a frame number")

check(ac.split_frame("c:/p/geo/noframe.bgeo.sc") is None, "no frame number")
check(ac.split_frame("c:/p/geo/v2.exr") is None, "two digits is not a frame")

# -- .bgeo.sc sequences must group -----------------------------------------

orphans = [ac.Orphan("c:/proj/geo/cache.%04d.bgeo.sc" % i, "c:/proj",
                     ac.SAFE_NEVER) for i in range(1, 51)]
groups = ac.group_orphans(orphans)
check(len(groups) == 1, "50 bgeo.sc frames collapse to one row")
check(groups[0].count == 50, "and the row holds all of them")
check("[0001-0050]" in groups[0].name, "with the span in the name")
check(".bgeo.sc" in groups[0].name, "and the compound extension intact")

# -- the stem safety net ---------------------------------------------------
# Every reference registers its sequence stem, whatever form it took, so a
# glob that resolves nothing still protects the frames on disk.

tmp = tempfile.mkdtemp(prefix="cleaner_frames_")
try:
    root = os.path.join(tmp, "proj").replace("\\", "/")
    os.makedirs(root + "/geo")
    for i in range(1, 6):
        with open(root + "/geo/cache.%04d.bgeo.sc" % i, "wb") as handle:
            handle.write(b"x")

    class FakeParm(object):
        def __init__(self, value):
            self._value = value
            self._node = types.SimpleNamespace(path=lambda: "/obj/f")

        def unexpandedString(self):
            return self._value

        def eval(self):
            return self._value

        def node(self):
            return self._node

        def name(self):
            return "file"

    ac.hou.hipFile = types.SimpleNamespace(path=lambda: root + "/cur.hip")

    def scan_with(value):
        ac._iter_file_parms = lambda: iter([(FakeParm(value), None)])
        return ac.scan(root, check_other_scenes=False)[0]

    # A $F4 reference whose frames exist: nothing is an orphan.
    orphans = scan_with(root + "/geo/cache.$F4.bgeo.sc")
    check(orphans == [], "a resolving $F4 protects every frame")

    # One explicit frame: the others are flagged, never ticked.
    orphans = scan_with(root + "/geo/cache.0001.bgeo.sc")
    check(len(orphans) == 4, "the other four frames are listed")
    check(all(o.reason == ac.SAFE_PARTIAL_SEQ for o in orphans),
          "as partial sequence, not never referenced")
    check(not any(o.selected for o in orphans),
          "and NONE of them are ticked for deletion")

    # A reference whose glob resolves nothing at all -- wrong padding. The
    # stem still has to protect what is on disk.
    orphans = scan_with(root + "/geo/cache.$F8.bgeo.sc")
    check(not any(o.selected for o in orphans),
          "a sequence that resolves nothing still protects its frames")
    check(all(o.reason == ac.SAFE_PARTIAL_SEQ for o in orphans),
          "and they are flagged rather than called never referenced")

    # -- quoting and whitespace on a parameter value ----------------------

    for messy in ('  ' + root + '/geo/cache.0001.bgeo.sc  ',
                  '"' + root + '/geo/cache.0001.bgeo.sc"'):
        orphans = scan_with(messy)
        names = [o.name for o in orphans]
        check("cache.0001.bgeo.sc" not in names,
              "a quoted or padded path still matches the file on disk")

    # -- a reference that belongs to no parameter -------------------------
    # hou.fileReferences() reports (None, path) for paths Houdini tracks
    # itself. Dropping those is another way a used file gets called unused.

    ac._iter_file_parms = lambda: iter(
        [(None, root + "/geo/cache.0003.bgeo.sc")])
    orphans = ac.scan(root, check_other_scenes=False)[0]
    names = [o.name for o in orphans]
    check("cache.0003.bgeo.sc" not in names,
          "a parm-less reference still protects its file")
    check(not any(o.selected for o in orphans),
          "and its sequence neighbours are not ticked either")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

done("test_frames")
