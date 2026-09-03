"""
Moving files out and putting them back, on real files in a temp folder.

The point of the move design is that it is reversible, so most of these tests
are about the round trip landing every file exactly where it started.
"""
import os
import shutil
import tempfile

import _stub
from _stub import check, done

import asset_cleaner as ac

tmp = tempfile.mkdtemp(prefix="cleaner_move_")
try:
    root = os.path.join(tmp, "proj").replace("\\", "/")
    tex = root + "/tex"
    geo = root + "/geo/caches"
    os.makedirs(tex)
    os.makedirs(geo)

    def write(path, content=b"data"):
        with open(path, "wb") as handle:
            handle.write(content)
        return path.replace("\\", "/")

    a = write(tex + "/a.exr", b"a" * 100)
    b = write(tex + "/b.exr", b"b" * 200)
    deep = write(geo + "/c.bgeo.sc", b"c" * 50)

    orphans = [ac.Orphan(p, root, ac.SAFE_NEVER) for p in (a, b, deep)]

    check(orphans[0].size_bytes == 100, "size read from disk")
    check(orphans[0].relative == "tex/a.exr", "relative path")
    check(orphans[2].relative == "geo/caches/c.bgeo.sc", "nested relative")
    check(orphans[2].folder == "geo/caches", "folder column")
    check(orphans[0].dest == root + "/_unused/tex/a.exr", "destination")

    # -- move out ---------------------------------------------------------

    moved, freed, errors = ac.move_out(orphans)
    check(moved == 3, "three files moved")
    check(freed == 350, "freed bytes totalled")
    check(not errors, "no errors: " + str(errors))

    check(not os.path.exists(a), "source gone")
    check(os.path.isfile(root + "/_unused/tex/a.exr"), "landed in _unused")
    check(os.path.isfile(root + "/_unused/geo/caches/c.bgeo.sc"),
          "nested structure preserved")

    count, size = ac.unused_size(root)
    check(count == 3 and size == 350, "unused_size reports the folder")

    # The walk must not offer files in _unused as fresh orphans.
    check(ac.walk_project(root) == [], "_unused is not walked")

    # -- restore ----------------------------------------------------------

    restored, errors = ac.restore(root)
    check(restored == 3, "three files restored")
    check(not errors, "no restore errors: " + str(errors))

    check(os.path.isfile(a), "back where it started")
    check(os.path.isfile(deep), "nested file back where it started")
    with open(a, "rb") as handle:
        check(handle.read() == b"a" * 100, "content survived the round trip")

    check(not os.path.exists(root + "/_unused/tex"),
          "empty skeleton cleaned up")

    # -- collisions --------------------------------------------------------

    # Something already in _unused with the same name must not be clobbered.
    os.makedirs(root + "/_unused/tex", exist_ok=True)
    write(root + "/_unused/tex/a.exr", b"older copy")
    ac.move_out([ac.Orphan(a, root, ac.SAFE_NEVER)])
    with open(root + "/_unused/tex/a.exr", "rb") as handle:
        check(handle.read() == b"older copy", "existing file not overwritten")
    check(os.path.isfile(root + "/_unused/tex/a_1.exr"),
          "collision got a _1 suffix")

    # Restoring when the original name is occupied must not destroy it.
    write(a, b"a file is back here now")
    restored, errors = ac.restore(root)
    with open(a, "rb") as handle:
        check(handle.read() == b"a file is back here now",
              "occupied original left alone")
    check(any("already back in place" in e for e in errors),
          "the skip is reported, not silent")

    # -- failure handling --------------------------------------------------

    ghost = ac.Orphan(root + "/tex/never_existed.exr", root, ac.SAFE_NEVER)
    moved, freed, errors = ac.move_out([ghost])
    check(moved == 0, "a file that vanished moves nothing")
    check(len(errors) == 1, "and is reported as an error")

    # Cancelling partway through stops the run.
    for name in ("x1.exr", "x2.exr", "x3.exr"):
        write(tex + "/" + name)
    batch = [ac.Orphan(tex + "/" + n, root, ac.SAFE_NEVER)
             for n in ("x1.exr", "x2.exr", "x3.exr")]
    moved, freed, errors = ac.move_out(
        batch, progress=lambda i, t, o: i < 1)
    check(moved == 1, "cancel stopped after the first file")
    check(any("Cancelled" in e for e in errors), "cancel is reported")

    # Restoring an empty project says so rather than raising.
    empty = os.path.join(tmp, "empty").replace("\\", "/")
    os.makedirs(empty)
    restored, errors = ac.restore(empty)
    check(restored == 0 and errors, "nothing to restore is reported")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

done("test_move")
