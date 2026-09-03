"""
Collapsing frame sequences into one row each.

Grouping is display-only: the Orphan objects underneath are still what gets
moved, so these tests care most that a group never loses a file and never
hides a protected one behind a safe-looking label.
"""
import _stub
from _stub import check, done

import asset_cleaner as ac

ROOT = "c:/proj"


def orphan(rel, reason=ac.SAFE_NEVER):
    o = ac.Orphan(ROOT + "/" + rel, ROOT, reason)
    o.size_bytes = 100          # os.stat found nothing; these are not real
    o.mtime = 1000
    return o


# -- frame numbers ---------------------------------------------------------

check(ac.frame_number("c:/p/beauty.0007.exr") == 7, "frame parsed")
check(ac.frame_width("c:/p/beauty.0007.exr") == 4, "padding kept")
check(ac.frame_number("c:/p/beauty.exr") is None, "no frame")
check(ac.frame_number("c:/p/v2.exr") is None, "two digits is not a frame")

# -- grouping --------------------------------------------------------------

seq = [orphan("render/beauty.%04d.exr" % i) for i in range(1, 241)]
singles = [orphan("tex/wall.exr"), orphan("tex/floor.jpg")]

groups = ac.group_orphans(seq + singles)
check(len(groups) == 3, "240 frames plus 2 singles collapse to 3 rows")

seq_group = groups[0]
check(seq_group.is_sequence, "the first row is a sequence")
check(seq_group.count == 240, "and holds every frame")
check("[0001-0240]" in seq_group.name, "the name shows the span")
check("240 files" in seq_group.name, "and the count")
check(seq_group.name.endswith("(240 files)"), "count comes last")
check(".exr" in seq_group.name, "the extension survives")

check(not groups[1].is_sequence, "a single file is a group of one")
check(groups[1].name == "wall.exr", "and keeps its plain name")

# Nothing may be lost or duplicated by grouping.
total = sum(g.count for g in groups)
check(total == len(seq) + len(singles), "every file is in exactly one group")

# -- what must NOT be grouped ---------------------------------------------

mixed = [orphan("geo/cache.0001.bgeo"), orphan("geo/cache.0001.exr")]
check(len(ac.group_orphans(mixed)) == 2,
      "same stem, different extension is not one sequence")

folders = [orphan("a/beauty.0001.exr"), orphan("b/beauty.0002.exr")]
check(len(ac.group_orphans(folders)) == 2,
      "same name in different folders is not one sequence")

check(len(ac.group_orphans(seq, enabled=False)) == 240,
      "grouping can be turned off")

# -- size, age and the representative path --------------------------------

check(seq_group.size_bytes == 240 * 100, "size is the whole sequence")
seq[5].mtime = 9999
check(seq_group.mtime == 9999, "age follows the newest frame")
check(seq_group.path == seq[0].path, "path is the first frame")
check(seq_group.folder == "render", "folder is shared")
check(seq_group.ext_label == "EXR", "type is shared")

# -- selection travels to every frame -------------------------------------

seq_group.selected = False
check(not any(o.selected for o in seq), "unticking the row unticks each frame")
seq_group.selected = True
check(all(o.selected for o in seq), "and ticking it ticks each frame")
check(seq_group.selected, "the row reads as ticked")

seq[3].selected = False
check(not seq_group.selected, "one unticked frame unticks the row")
check(seq_group.partially_selected, "and the row reports itself as partial")
seq_group.selected = True

# -- the row must show the most cautious reason ---------------------------
# Ticking a row moves every frame in it, so a group holding one protected
# frame must not advertise itself as safe.

risky = [orphan("render/x.0001.exr"),
         orphan("render/x.0002.exr", ac.SAFE_OTHER_SCENE)]
group = ac.group_orphans(risky)[0]
check(group.count == 2, "grouped despite differing reasons")
check(group.reason == ac.SAFE_OTHER_SCENE,
      "the row shows the protected reason, not the safe one")

partial = [orphan("render/y.0001.exr"),
           orphan("render/y.0002.exr", ac.SAFE_PARTIAL_SEQ)]
check(ac.group_orphans(partial)[0].reason == ac.SAFE_PARTIAL_SEQ,
      "partial sequence outranks never referenced")

# other_scenes is merged without duplicates.
risky[0].other_scenes = ["a.hip"]
risky[1].other_scenes = ["a.hip", "b.hip"]
check(group.other_scenes == ["a.hip", "b.hip"], "scene list is deduplicated")

done("test_group")
