"""
Render and comp output.

A render is not an orphan: nothing reads it back, which is the whole point of
an output. Judging it by "does anything reference this" is meaningless, and
listing thousands of ticked frames buries the orphans that matter.
"""
import os
import shutil
import tempfile
import types

import _stub
from _stub import check, done

import asset_cleaner as ac

# -- folder names ----------------------------------------------------------

for name in ("render", "renders", "Render", "comp", "comps", "compositing",
             "frames", "flipbook", "playblast", "out", "output", "preview",
             "proxy", "05_render", "3_comp", "010_output", "_render",
             "render_v03", "render2", "COMP"):
    check(ac.is_output_dir_name(name), name + " reads as output")

for name in ("tex", "geo", "abc", "scenes", "rendering_notes", "compare",
             "components", "outfit", "framework", "reference", "source"):
    check(not ac.is_output_dir_name(name), name + " is NOT output")

# -- paths -----------------------------------------------------------------

ROOT = "f:/proj/shot01"

check(ac.in_output_folder(ROOT + "/render/beauty.0001.exr", ROOT),
      "a frame under render/ is output")
check(ac.in_output_folder(ROOT + "/MIC_perf/comp/x.0001.jpg", ROOT),
      "comp/ nested deeper is output")
check(not ac.in_output_folder(ROOT + "/tex/wall.exr", ROOT),
      "a texture is not output")

# The project root itself must not be searched for output words, or a project
# living in D:/renders/shot01 would call every one of its files an output.
check(not ac.in_output_folder("d:/renders/shot01/tex/wall.exr",
                              "d:/renders/shot01"),
      "an output word in the ROOT path is ignored")

# A ROP output folder is honoured even when its name says nothing.
check(ac.in_output_folder(ROOT + "/deliver/final.0001.exr", ROOT,
                          [ROOT + "/deliver"]),
      "a folder a ROP writes to is output whatever it is called")
check(not ac.in_output_folder(ROOT + "/deliverables/brief.exr", ROOT,
                              [ROOT + "/deliver"]),
      "and prefix is not containment")

# -- the verdict is never recommended --------------------------------------

check(ac.SAFE_OUTPUT not in ac.AUTO_SELECT,
      "render output is NEVER ticked automatically")
check(ac.SAFE_OUTPUT in ac.CONFIDENCE_HELP, "it has help text")
check(ac.SAFE_OUTPUT in ac.CONFIDENCE_COLOURS, "and a colour")

# -- end to end ------------------------------------------------------------

tmp = tempfile.mkdtemp(prefix="cleaner_out_")
try:
    root = os.path.join(tmp, "proj").replace("\\", "/")
    for sub in ("render", "comp", "tex", "deliver"):
        os.makedirs(root + "/" + sub)

    for i in range(1, 6):
        with open(root + "/render/beauty.%04d.exr" % i, "wb") as fh:
            fh.write(b"x" * 10)
        with open(root + "/comp/final.%04d.jpg" % i, "wb") as fh:
            fh.write(b"x" * 10)
        with open(root + "/deliver/out.%04d.exr" % i, "wb") as fh:
            fh.write(b"x" * 10)
    with open(root + "/tex/wall.exr", "wb") as fh:
        fh.write(b"x" * 10)

    class FakeParm(object):
        def __init__(self, value, name):
            self._value = value
            self._name = name
            self._node = types.SimpleNamespace(path=lambda: "/out/rop")

        def unexpandedString(self):
            return self._value

        def eval(self):
            return self._value

        def node(self):
            return self._node

        def name(self):
            return self._name

    ac.hou.hipFile = types.SimpleNamespace(path=lambda: root + "/cur.hip")

    # A ROP writing into deliver/ -- a folder whose name says nothing.
    ac._iter_file_parms = lambda: iter(
        [(FakeParm(root + "/deliver/out.$F4.exr", "sopoutput"), None)])
    orphans, _ = ac.scan(root, check_other_scenes=False)
    by_name = {o.name: o for o in orphans}

    check(by_name["beauty.0001.exr"].reason == ac.SAFE_OUTPUT,
          "render/ is output by name")
    check(by_name["final.0001.jpg"].reason == ac.SAFE_OUTPUT,
          "comp/ is output by name")
    check(by_name["wall.exr"].reason == ac.SAFE_NEVER,
          "a texture is still a plain orphan")

    check(not any(o.selected for o in orphans
                  if o.reason == ac.SAFE_OUTPUT),
          "no output file is ticked")
    check(by_name["wall.exr"].selected, "but the real orphan still is")

    # The deliver/ frames were written by the ROP, so they resolve as used
    # rather than merely being output -- either way, never ticked.
    delivered = [o for o in orphans if o.name.startswith("out.")]
    check(not any(o.selected for o in delivered),
          "frames a ROP writes are never ticked")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

done("test_output")
