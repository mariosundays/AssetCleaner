"""
Reading asset paths out of a .hip file without opening it.

A .hip is a CPIO archive whose payload is plain hscript text, so the paths are
recoverable with a string scan. These tests build a file with that shape --
binary header, printable payload -- and check what comes back out.
"""
import os
import shutil
import tempfile

import _stub
from _stub import check, done

import asset_cleaner as ac

tmp = tempfile.mkdtemp(prefix="cleaner_hip_")
try:
    root = os.path.join(tmp, "proj").replace("\\", "/")
    tex = os.path.join(root, "tex").replace("\\", "/")
    os.makedirs(tex)

    # Real files, so the "on disk" side of the report is real too.
    for name in ("used.exr", "shared.exr", "fire.0001.exr", "fire.0002.exr"):
        with open(os.path.join(tex, name), "wb") as handle:
            handle.write(b"x" * 32)

    def write_hip(path, body):
        """A file shaped like a .hip: binary noise plus printable hscript."""
        with open(path, "wb") as handle:
            handle.write(b"070707000001000000000666\x00\x01\x02")
            handle.write(body.encode("utf-8"))
            handle.write(b"\x00\xff\xfe")

    scene = os.path.join(root, "other.hip").replace("\\", "/")
    write_hip(scene, (
        "set -g ACTIVETAKE = 'Main'\n"
        "opparm /obj/geo1/file1 file ( '{tex}/shared.exr' )\n"
        "opparm /obj/geo1/file2 file ( '$HIP/tex/used.exr' )\n"
        "opparm /obj/geo1/file3 file ( '$HIP/tex/fire.$F4.exr' )\n"
        "opparm /obj/geo1/file4 file ( 'D:/library/outside.exr' )\n"
        "opparm /obj/geo1/rop   sopoutput ( '$HIP/geo/gone.bgeo.sc' )\n"
    ).format(tex=tex))

    found = ac.paths_in_hip(scene, root, root)

    check(ac._key(tex + "/shared.exr") in found, "absolute path found")
    check(ac._key(tex + "/used.exr") in found, "$HIP expanded")
    check(ac._key("D:/library/outside.exr") in found,
          "path outside the project still reported")
    check(ac._key(root + "/geo/gone.bgeo.sc") in found,
          "compound extension matched")
    check(ac._key("D:/library/outside.exr") in found, "other drive kept")

    # A sequence expands to the frames actually on disk.
    check(ac._key(tex + "/fire.0001.exr") in found, "sequence frame 1")
    check(ac._key(tex + "/fire.0002.exr") in found, "sequence frame 2")

    # A missing reference is still reported -- erring toward "in use".
    check(any("gone.bgeo.sc" in p for p in found),
          "reference that is not on disk is still reported")

    # -- unresolvable variables ($HIPNAME, $SF) ---------------------------
    # These survive eval(); globbing them is what stops a live sim cache
    # from being reported as unused.

    os.makedirs(root + "/sim")
    for n in ("cache.myscene.windows_nt.1.sim",
              "cache.myscene.windows_nt.2.sim"):
        with open(root + "/sim/" + n, "wb") as handle:
            handle.write(b"x")

    var_scene = root + "/vars.hip"
    write_hip(var_scene, "opparm /obj/d filename ( "
                         "'$HIP/sim/cache.$HIPNAME.windows_nt.$SF.sim' )")
    got = ac.paths_in_hip(var_scene, root, root)
    real = [p for p in got if os.path.exists(p)]
    check(len(real) == 2, "a $HIPNAME/$SF cache path matches its real files")
    check(any("$hipname" in p for p in got),
          "the unresolved form is kept as well, for the reference count")

    # -- sibling discovery ------------------------------------------------

    open(os.path.join(root, "current.hip"), "wb").write(b"070707\x00")
    hips = ac.find_sibling_hips(root, os.path.join(root, "current.hip"))
    check(len(hips) == 2, "the open scene is excluded from siblings")
    check(not any(h.endswith("current.hip") for h in hips),
          "and it really is the open one that is gone")
    check(any(h.endswith("other.hip") for h in hips), "the others are found")

    # A .hip inside _unused must not count as a user of anything.
    unused_dir = os.path.join(root, "_unused")
    os.makedirs(unused_dir)
    write_hip(os.path.join(unused_dir, "archived.hip"), "opparm x ( 'a.exr' )")
    hips = ac.find_sibling_hips(root, os.path.join(root, "current.hip"))
    check(len(hips) == 2, "_unused is not walked for scenes")
    check(not any("_unused" in h for h in hips), "nothing from _unused")

    # -- the whole report --------------------------------------------------

    scenes, used_by = ac.scan_other_scenes(
        root, os.path.join(root, "current.hip"))
    check(len(scenes) == 2, "both sibling scenes reported")

    scene_ref = [s for s in scenes if s.name == "other.hip"][0]
    check(scene_ref.name == "other.hip", "scene name")
    check(len(scene_ref.inside_paths) < len(scene_ref.all_paths),
          "the outside reference is excluded from the in-project count")
    check(any("gone.bgeo.sc" in p for p in scene_ref.missing),
          "missing references are counted")
    check(ac._key(tex + "/shared.exr") in used_by, "used_by maps the file")
    check(used_by[ac._key(tex + "/shared.exr")][0].endswith("other.hip"),
          "used_by names the scene")

    # An unreadable file must not take the scan down.
    check(ac.paths_in_hip(os.path.join(root, "nope.hip")) == set(),
          "missing hip returns empty, does not raise")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

done("test_hipscan")
