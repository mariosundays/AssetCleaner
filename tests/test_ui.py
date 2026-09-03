"""
The UI layer, as far as it can be exercised without a real Qt.

Qt is stubbed, so this cannot prove the window looks right. What it does
prove is that every method referenced by a signal actually exists and that
the column constants line up with the headers -- the mistakes that otherwise
only show up as a traceback in the Houdini console.
"""
import _stub
from _stub import check, done

import asset_cleaner as ac

# -- column layout ---------------------------------------------------------

check(ac.COL_ON == 0, "the checkbox is the first column")
check(len({ac.COL_ON, ac.COL_EXT, ac.COL_FILE, ac.COL_FOLDER,
           ac.COL_REASON, ac.COL_SIZE, ac.COL_AGE}) == 7,
      "the seven column ids are distinct")
check(len({ac.SCOL_SCENE, ac.SCOL_FOLDER, ac.SCOL_USES, ac.SCOL_INSIDE,
           ac.SCOL_MISSING, ac.SCOL_AGE}) == 6,
      "the six scene column ids are distinct")

# -- every slot a signal connects to must exist ---------------------------

for name in ("_browse_root", "refresh", "_run", "_restore",
             "_select_recommended", "_select_all", "_select_none",
             "_select_invert", "_on_item_changed", "_on_double_click",
             "_context_menu", "_header_double_clicked", "_on_section_resized",
             "_on_scene_selected", "_on_scene_double_click",
             "_scene_files_menu", "_show_users", "_move_refs",
             "_scan_scenes", "_cancel_scene_scan", "_open_file",
             "_regroup", "_toggle_grouping", "_explain",
             "fit_columns", "_populate", "_populate_scenes",
             "_fill_ref_table", "_update_status", "_update_legend",
             "_apply_states", "_reveal", "_ref_at", "_scene_at"):
    check(hasattr(ac.CleanerDialog, name), "CleanerDialog." + name)

check(hasattr(ac, "main"), "module entry point")

# -- colours are defined for everything the tables display ----------------

check(ac.ext_colour("EXR") == ac.EXT_COLOURS["exr"], "known extension")
check(ac.ext_colour("ZZZ") == ac.DEFAULT_EXT_COLOUR, "unknown extension")
check(ac.ext_colour("") == ac.DEFAULT_EXT_COLOUR, "empty extension")
check(ac.ext_colour(None) == ac.DEFAULT_EXT_COLOUR, "None extension")

# -- sortable cells --------------------------------------------------------

items = [ac.SortableItem("1.0 MB", 1048576),
         ac.SortableItem("999 B", 999),
         ac.SortableItem("1.5 KB", 1536)]
order = [i._key for i in sorted(items)]
check(order == [999, 1536, 1048576], "size sorts by bytes, not by text")

# Mixed key types must fall back to string rather than raising.
mixed = sorted([ac.SortableItem("a", 1), ac.SortableItem("b", "x")])
check(len(mixed) == 2, "mixed sort keys do not raise")

# -- the sibling scan is opt-in -------------------------------------------

import inspect

src = inspect.getsource(ac.CleanerDialog.refresh)
check("check_other_scenes=False" in src,
      "refresh must not read the other scenes -- that is what made it slow")

src = inspect.getsource(ac.CleanerDialog._scan_scenes)
check("scan_other_scenes" in src, "the button is what reads them")
check("processEvents" in src, "the progress bar has to be pumped to move")
check("_scene_scan_cancelled" in src, "and Cancel has to be honoured")

sig = inspect.signature(ac.scan)
check(sig.parameters["check_other_scenes"].default is False,
      "scan() defaults to the open scene only")

check(ac.WARN_STYLE != ac.INFO_STYLE,
      "the unscanned banner looks different from the scanned one")

# -- the scene walk must use the fast path --------------------------------
# parmTemplate() on every parm of every node is tens of thousands of C++
# crossings and took ~30s to open on a real scene. hou.fileReferences() is
# one call. If this assertion ever fails, the window got slow again.

src = inspect.getsource(ac._iter_file_parms)
check("fileReferences" in src, "the scene walk uses hou.fileReferences()")
check(src.index("fileReferences") < src.index("allSubChildren"),
      "and the slow walk is only the fallback, not the first choice")

src = inspect.getsource(ac.scene_references)
check("supplied" in src,
      "the expanded path from fileReferences() is reused, not re-eval()ed")

# -- opening a file -------------------------------------------------------

src = inspect.getsource(ac.CleanerDialog._open_file)
check("startfile" in src, "Windows uses startfile")
check("xdg-open" in src and "darwin" in src, "mac and linux are handled too")
check("isfile" in src, "a file that has gone is reported, not silently ignored")

src = inspect.getsource(ac.CleanerDialog._on_double_click)
check("_open_file" in src, "double-click opens the file itself")

# -- grouping is wired into the table -------------------------------------

src = inspect.getsource(ac.CleanerDialog._populate)
check("self.groups" in src, "the table renders groups, not raw orphans")
check("PartiallyChecked" in src, "a part-ticked sequence shows as partial")

src = inspect.getsource(ac.CleanerDialog._ref_at)
check("self.groups" in src, "a row resolves to its group")

src = inspect.getsource(ac.CleanerDialog._move_refs)
check("orphans" in src and "getattr" in src,
      "moving flattens groups back to individual files")

src = inspect.getsource(ac.CleanerDialog._context_menu)
check("g.count" in src, "the menu counts files, not rows")

done("test_ui")
