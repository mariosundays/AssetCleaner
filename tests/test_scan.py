"""
The whole scan, with a fake Houdini scene wired up.

This is the test that matters most: it checks a file another scene uses is
downgraded so it is never ticked, which is the safety property the tool
depends on.
"""
import os
import shutil
import tempfile
import types

import _stub
from _stub import check, done

import asset_cleaner as ac

tmp = tempfile.mkdtemp(prefix="cleaner_scan_")
try:
    root = os.path.join(tmp, "proj").replace("\\", "/")
    tex = root + "/tex"
    os.makedirs(tex)

    def write(path, content=b"data"):
        with open(path, "wb") as handle:
            handle.write(content)
        return path.replace("\\", "/")

    used = write(tex + "/used.exr")
    orphan = write(tex + "/orphan.exr")
    shared = write(tex + "/shared.exr")
    backup = write(tex + "/thing_bak.exr")
    write(tex + "/notes.txt")           # not an asset type -- never listed

    # --- a fake scene referencing only used.exr -------------------------

    class FakeParm(object):
        def __init__(self, value, node_path="/obj/geo1/file1"):
            self._value = value
            self._node = types.SimpleNamespace(path=lambda: node_path)

        def unexpandedString(self):
            return self._value

        def eval(self):
            return self._value

        def node(self):
            return self._node

        def name(self):
            return "file"

    ac._iter_file_parms = lambda: iter([FakeParm(used)])
    ac.hou.hipFile = types.SimpleNamespace(
        path=lambda: root + "/current.hip")

    paths, stems, by_path = ac.scene_references()
    check(ac._key(used) in paths, "the referenced file is in the used set")
    check(by_path[ac._key(used)] == ["/obj/geo1/file1"],
          "used set records which node referenced it")

    # --- a sibling scene that uses shared.exr ----------------------------

    with open(root + "/other.hip", "wb") as handle:
        handle.write(b"070707\x00")
        handle.write(("opparm /obj/f file ( '$HIP/tex/shared.exr' )\n")
                     .encode())

    # The default must NOT read the other scenes -- it is opt-in now.
    orphans, scenes = ac.scan(root)
    check(scenes == [], "the default scan does not read sibling scenes")
    check({o.name for o in orphans if o.selected} >= {"shared.exr"},
          "and so a file used only elsewhere IS ticked until you scan")

    orphans, scenes = ac.scan(root, check_other_scenes=True)
    by_name = {o.name: o for o in orphans}

    check("used.exr" not in by_name, "a referenced file is not an orphan")
    check("notes.txt" not in by_name, "non-asset files are never listed")
    check("orphan.exr" in by_name, "an unreferenced asset is an orphan")
    check("shared.exr" in by_name, "a file used only elsewhere is listed")
    check("thing_bak.exr" in by_name, "a backup is listed")

    check(by_name["orphan.exr"].reason == ac.SAFE_NEVER, "plain orphan")
    check(by_name["orphan.exr"].selected, "plain orphan is ticked")

    check(by_name["shared.exr"].reason == ac.SAFE_OTHER_SCENE,
          "the sibling scene downgrades it")
    check(not by_name["shared.exr"].selected,
          "a file another scene uses is NEVER ticked")
    check(by_name["shared.exr"].other_scenes,
          "and it records which scene uses it")

    check(by_name["thing_bak.exr"].selected, "backups are still ticked")

    check(len(scenes) == 1, "the sibling scene is reported")

    # --- without the sibling check ---------------------------------------

    orphans, scenes = ac.scan(root, check_other_scenes=False)
    by_name = {o.name: o for o in orphans}
    check(scenes == [], "no scene report when the check is off")
    check(by_name["shared.exr"].selected,
          "without the check, the shared file WOULD be ticked -- which is "
          "exactly why the check exists")

    # --- applying the scan afterwards, the way the button does --------------

    orphans, _ = ac.scan(root)                      # open scene only
    before = [o.name for o in orphans if o.selected]
    check("shared.exr" in before, "ticked before the sibling scan")

    scenes, used_by = ac.scan_other_scenes(root, root + "/current.hip")
    changed = ac.apply_other_scenes(orphans, used_by)
    after = [o.name for o in orphans if o.selected]

    check(changed == 1, "one orphan was downgraded")
    check("shared.exr" not in after,
          "applying the scan afterwards unticks it, without a full rescan")
    check(ac.SAFE_OTHER_SCENE in {o.reason for o in orphans},
          "and marks it as used by another scene")

    # --- a root that does not exist ---------------------------------------

    orphans, scenes = ac.scan(os.path.join(tmp, "nope"))
    check(orphans == [] and scenes == [], "missing root returns empty")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

done("test_scan")
