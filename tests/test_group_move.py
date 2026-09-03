"""
Grouping must not change what actually happens on disk.

A sequence row stands for every frame in it, so ticking one row and pressing
the button has to move all of them -- and moving must still be per-file.
"""
import os
import shutil
import tempfile

import _stub
from _stub import check, done

import asset_cleaner as ac

tmp = tempfile.mkdtemp(prefix="cleaner_gmove_")
try:
    root = os.path.join(tmp, "proj").replace("\\", "/")
    render = root + "/render"
    os.makedirs(render)

    for i in range(1, 25):
        with open(render + "/beauty.%04d.exr" % i, "wb") as handle:
            handle.write(b"x" * 10)
    with open(render + "/note.jpg", "wb") as handle:
        handle.write(b"y" * 5)

    orphans = [ac.Orphan(render + "/beauty.%04d.exr" % i, root, ac.SAFE_NEVER)
               for i in range(1, 25)]
    orphans.append(ac.Orphan(render + "/note.jpg", root, ac.SAFE_NEVER))

    groups = ac.group_orphans(orphans)
    check(len(groups) == 2, "24 frames plus a jpg make 2 rows")

    seq = groups[0]
    check(seq.count == 24, "the sequence row holds 24 files")
    check(seq.size_bytes == 240, "and reports their combined size")

    # Moving the row must move every frame, the same way the UI flattens it.
    flat = []
    for row in [seq]:
        flat.extend(getattr(row, "orphans", [row]))
    moved, freed, errors = ac.move_out(flat)

    check(moved == 24, "every frame moved")
    check(freed == 240, "freed size is the whole sequence")
    check(not errors, "no errors: " + str(errors))

    check(not os.path.exists(render + "/beauty.0001.exr"), "frames gone")
    check(os.path.isfile(root + "/_unused/render/beauty.0024.exr"),
          "frames landed in _unused keeping their folder")
    check(os.path.isfile(render + "/note.jpg"),
          "the file that was NOT in the row is untouched")

    # And restore brings the whole sequence back.
    restored, errors = ac.restore(root)
    check(restored == 24, "the whole sequence restored")
    check(os.path.isfile(render + "/beauty.0001.exr"), "back where it started")

    # -- a group with one protected frame ---------------------------------
    # Ticking a row moves everything in it, so the row must not look safe.

    mixed = [ac.Orphan(render + "/beauty.%04d.exr" % i, root, ac.SAFE_NEVER)
             for i in range(1, 5)]
    mixed[2].reason = ac.SAFE_OTHER_SCENE
    mixed[2].selected = False
    group = ac.group_orphans(mixed)[0]

    check(group.reason == ac.SAFE_OTHER_SCENE,
          "the row shows the protected reason")
    check(group.reason not in ac.AUTO_SELECT,
          "so Select recommended will not tick it")
    check(group.partially_selected, "and it reads as partly ticked")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

done("test_group_move")
