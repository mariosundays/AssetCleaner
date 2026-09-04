"""
Scenes whose file paths are built by expression.

A File Cache node assembles its path at cook time:

    `chs("basedir") + "/" + chs("basename")` + version + frame + filetype

With the scene OPEN this is a non-issue -- Houdini evaluates it and
hou.fileReferences() hands back a real path. Reading a CLOSED sibling scene
as text is where it bites: the backtick string is all that is there, so a
scene can reference a whole cache directory without one literal path
appearing in the file.

The folder is still recoverable: "basedir" holds a literal "$HIP/geo". That
is enough to protect what is inside it without pretending to evaluate
anything.
"""
import os
import shutil
import tempfile

import _stub
from _stub import check, done

import asset_cleaner as ac

tmp = tempfile.mkdtemp(prefix="cleaner_expr_")
try:
    root = os.path.join(tmp, "proj").replace("\\", "/")
    for sub in ("geo", "tex", "abc"):
        os.makedirs(root + "/" + sub)

    for i in range(1, 6):
        with open(root + "/geo/flower.%04d.bgeo.sc" % i, "wb") as handle:
            handle.write(b"x" * 10)
    with open(root + "/tex/orphan.exr", "wb") as handle:
        handle.write(b"x" * 10)
    with open(root + "/abc/model.abc", "wb") as handle:
        handle.write(b"x" * 10)

    def write_hip(path, body):
        with open(path, "wb") as handle:
            handle.write(b"070707000001000000000666\x00\x01\x02")
            handle.write(body.encode("utf-8"))
            handle.write(b"\x00\xff\xfe")

    # A sibling shaped like the real File Cache: an expression for the file,
    # and basedir holding the folder as a plain string.
    sibling = root + "/sibling.hip"
    write_hip(sibling, (
        '        name    "basedir"\n'
        '        default { "$HIP/geo" }\n'
        '        name    "file"\n'
        '        default { "`chs(\\"basedir\\") + \\"/\\" '
        '+ chs(\\"basename\\")`" }\n'
    ))

    # Nothing literal to find -- that is the whole problem.
    literal = ac.paths_in_hip(sibling, root, root)
    check(not any("flower" in p for p in literal),
          "no literal cache path appears in a scene built by expression")

    # But the folder is recoverable.
    folders = ac.folders_in_hip(sibling, root, root)
    check(ac._key(root + "/geo") in folders, "the basedir folder is recovered")

    # The project root itself must never be protected -- it would excuse
    # every file in the project and make the tool useless.
    check(ac._key(root) not in folders, "the project root is never a folder")

    # A folder that does not exist on disk is not protected either.
    write_hip(root + "/ghost.hip", '  default { "$HIP/nowhere" }\n')
    check(not ac.folders_in_hip(root + "/ghost.hip", root, root),
          "a folder that is not on disk protects nothing")

    # -- end to end --------------------------------------------------------

    scenes, used_by, scene_folders = ac.scan_other_scenes(
        root, root + "/current.hip")
    check(ac._key(root + "/geo") in scene_folders,
          "the sibling scan reports the folder")

    # The OPEN scene references nothing here -- this is about the sibling.
    ac._iter_file_parms = lambda: iter([])
    orphans, _ = ac.scan(root, check_other_scenes=False)
    before = {o.name: o for o in orphans}
    check(before["flower.0001.bgeo.sc"].selected,
          "without the sibling scan the cache frames are ticked")

    changed = ac.apply_other_scenes(orphans, used_by, scene_folders)
    after = {o.name: o for o in orphans}

    check(changed >= 5, "the cache frames were downgraded")
    check(after["flower.0001.bgeo.sc"].reason == ac.SAFE_OTHER_SCENE,
          "a cache built by expression is credited to the sibling scene")
    check(not after["flower.0001.bgeo.sc"].selected,
          "and is NOT ticked -- this is the re-sim it saves")
    check(after["orphan.exr"].selected,
          "a real orphan in another folder is still ticked")

    # The scene is reported as carrying that folder, for the UI.
    sibling_ref = [s for s in scenes if s.name == "sibling.hip"][0]
    check(ac._key(root + "/geo") in sibling_ref.folders,
          "the SceneRef carries its folders")

    # -- cost -------------------------------------------------------------
    # Only folders inside the project are stat-ed. Without that filter a
    # scene naming ~90 distinct outside paths cost 0.8s in isdir() round
    # trips on a Dropbox share -- 70s across a 91-scene project.

    import inspect
    src = inspect.getsource(ac.folders_in_hip)
    check("is_inside(c, root)" in src,
          "candidates outside the project are dropped before any isdir()")
    check(src.index("candidates.add") < src.index("os.path.isdir"),
          "and the set is deduplicated before the filesystem is touched")

finally:
    shutil.rmtree(tmp, ignore_errors=True)

done("test_expressions")
