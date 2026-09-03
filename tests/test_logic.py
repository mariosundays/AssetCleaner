"""Path handling, extensions, sequences and the inside/outside test."""
import _stub
from _stub import check, done

import asset_cleaner as ac

# -- extensions ------------------------------------------------------------

check(ac.file_ext("C:/p/tex/a.EXR") == ".exr", "ext lowercased")
check(ac.file_ext("C:/p/geo/a.bgeo.sc") == ".bgeo.sc", "compound ext kept")
check(ac.file_ext("C:/p/geo/a.sc") == ".sc", "plain .sc untouched")
check(ac.file_ext("C:/p/noext") == "", "no extension")
check(ac.ext_label("C:/p/a.bgeo.sc") == "BGEO.SC", "compound label")
check(ac.ext_label("C:/p/noext") == "-", "empty label")

# -- inside / outside ------------------------------------------------------

check(ac.is_inside("C:/proj/tex/a.exr", "C:/proj"), "inside")
check(not ac.is_inside("D:/other/a.exr", "C:/proj"), "other drive outside")
check(not ac.is_inside("C:/projects2/a.exr", "C:/proj"),
      "prefix match is not containment")
check(not ac.is_inside("C:/proj/a.exr", ""), "empty root is never inside")
check(ac.is_inside("C:/PROJ/TEX/a.exr", "c:/proj"), "case insensitive")

# -- sequences -------------------------------------------------------------

check(ac.is_sequence("C:/p/f.$F4.exr"), "$F4 is a sequence")
check(ac.is_sequence("C:/p/f.%04d.exr"), "%04d is a sequence")
check(ac.is_sequence("C:/p/f.####.exr"), "#### is a sequence")
check(ac.is_sequence("C:/p/t.<UDIM>.exr"), "UDIM is a sequence")
check(not ac.is_sequence("C:/p/f.exr"), "plain file is not a sequence")

check(ac.sequence_stem("C:/p/fire.$F4.exr") == "c:/p/fire.", "stem of $F4")
check(ac.sequence_stem("C:/p/fire.exr") == "c:/p/fire.exr", "stem of plain")

# -- backup and version detection -----------------------------------------

check(ac.is_backup_name("C:/p/a_bak.exr"), "_bak")
check(ac.is_backup_name("C:/p/a_old.exr"), "_old")
check(ac.is_backup_name("C:/p/scene - Copy.exr"), "windows copy suffix")
check(not ac.is_backup_name("C:/p/backdrop.exr"),
      "'back' inside a word is not a backup")

check(ac.version_of("C:/p/a_v003.exr") == 3, "version parsed")
check(ac.version_of("C:/p/a.exr") is None, "no version")
check(ac.version_stem("C:/p/a_v003.exr") == ac.version_stem("C:/p/a_v012.exr"),
      "versions share a stem")

# -- classification --------------------------------------------------------

used = {"c:/proj/tex/used.exr", "c:/proj/geo/model.obj"}
stems = {"c:/proj/tex/fire."}
on_disk = ["C:/proj/tex/used.exr", "C:/proj/tex/spare.exr",
           "C:/proj/tex/a_v001.exr", "C:/proj/tex/a_v002.exr"]

check(ac.classify_orphan("C:/proj/tex/used.exr", used, stems, on_disk) is None,
      "used file is not an orphan")
check(ac.classify_orphan("C:/proj/tex/spare.exr", used, stems,
                         on_disk) == ac.SAFE_NEVER,
      "unreferenced file is an orphan")
check(ac.classify_orphan("C:/proj/tex/spare_bak.exr", used, stems,
                         on_disk) == ac.SAFE_BACKUP,
      "backup name wins")
check(ac.classify_orphan("C:/proj/tex/fire.0044.exr", used, stems,
                         on_disk) == ac.SAFE_PARTIAL_SEQ,
      "frame outside the used range is flagged, not silently dropped")
check(ac.classify_orphan("C:/proj/tex/a_v001.exr", used, stems,
                         on_disk) == ac.SAFE_VERSION,
      "older version detected")
check(ac.classify_orphan("C:/proj/tex/a_v002.exr", used, stems,
                         on_disk) == ac.SAFE_NEVER,
      "highest version is a plain orphan, not a version")
check(ac.classify_orphan("C:/proj/geo/model.mtl", used, stems,
                         on_disk) == ac.SAFE_SIDECAR,
      "mtl beside a used obj is a sidecar")

# A .tx sitting beside a used .exr belongs to it.
check(ac.classify_orphan("C:/proj/tex/used.tx", used, stems,
                         on_disk) == ac.SAFE_SIDECAR,
      "tx beside a used exr is a sidecar")

# -- what is ticked by default --------------------------------------------

check(ac.SAFE_NEVER in ac.AUTO_SELECT, "plain orphans are ticked")
check(ac.SAFE_BACKUP in ac.AUTO_SELECT, "backups are ticked")
for careful in (ac.SAFE_SIDECAR, ac.SAFE_OTHER_SCENE, ac.SAFE_PARTIAL_SEQ,
                ac.SAFE_VERSION):
    check(careful not in ac.AUTO_SELECT,
          "{} is never ticked automatically".format(careful))

# Every reason has help text and a colour, or the UI shows a blank cell.
for reason in (ac.SAFE_NEVER, ac.SAFE_BACKUP, ac.SAFE_VERSION,
               ac.SAFE_SIDECAR, ac.SAFE_OTHER_SCENE, ac.SAFE_PARTIAL_SEQ):
    check(reason in ac.CONFIDENCE_HELP, "help for " + reason)
    check(reason in ac.CONFIDENCE_COLOURS, "colour for " + reason)

# -- formatting ------------------------------------------------------------

check(ac._human(999) == "999 B", "bytes")
check(ac._human(1536) == "1.5 KB", "kilobytes")
check(ac._human(1048576) == "1.0 MB", "megabytes")


# -- leftover Houdini variables -------------------------------------------
# $HIPNAME/$OS/$SF survive eval() and cannot be resolved outside a session.
# They must glob, not be treated as one unmatchable literal filename.

check(ac.VARIABLE_RE.search("C:/p/cache.$HIPNAME.sim"), "$HIPNAME detected")
check(ac.VARIABLE_RE.search("C:/p/${FOO}/a.exr"), "${FOO} detected")
check(not ac.VARIABLE_RE.search("C:/p/plain.exr"), "plain path has no var")
check(ac.expand_glob("$HIP/tex/a.exr") == [],
      "a pattern that starts with a wildcard is refused, not walked")

# -- frame stems -----------------------------------------------------------
# A scene often points at ONE explicit frame rather than a $F pattern. The
# other frames must not then look like unrelated files.

check(ac.frame_stem("C:/p/tex/fire.0007.exr") == "c:/p/tex/fire.",
      "numbered frame stem")
check(ac.frame_stem("C:/p/tex/fire_0007.exr") == "c:/p/tex/fire_",
      "underscore frame stem")
check(ac.frame_stem("C:/p/tex/fire.exr") is None, "no number is not a frame")
check(ac.frame_stem("C:/p/tex/v2.exr") is None, "two digits is not a frame")
check(ac.sequence_stem("C:/p/tex/fire.$F4.exr")
      == ac.frame_stem("C:/p/tex/fire.0007.exr"),
      "$F4 and an explicit frame agree on the stem, or the match never fires")

# An explicit frame in the used set protects its neighbours...
explicit = {"c:/proj/tex/fire.0001.exr"}
frame_stems = {"c:/proj/tex/fire."}
check(ac.classify_orphan("C:/proj/tex/fire.0002.exr", explicit, frame_stems,
                         []) == ac.SAFE_PARTIAL_SEQ,
      "a neighbouring frame is a partial sequence, not a plain orphan")
check(ac.SAFE_PARTIAL_SEQ not in ac.AUTO_SELECT,
      "and so it is never ticked for removal")

# ...without swallowing a differently-named file that merely shares a prefix.
check(ac.classify_orphan("C:/proj/tex/fire_render.exr", explicit, frame_stems,
                         []) == ac.SAFE_NEVER,
      "a prefix match that is not a frame stays a plain orphan")

done("test_logic")
