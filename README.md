# Houdini Asset Cleaner

A Houdini tool that finds files in your project folder that nothing is using,
and moves them out of the way -- without deleting anything.

The companion to [Asset Consolidator](https://github.com/mariosundays/AssetConsolidator). That one pulls
outside files *in*; this one finds what is left over once you are done. Useful
before archiving a shot or handing a project on, when a folder has collected
years of test caches and texture versions nobody can identify any more.

[Scene Optimizer](https://github.com/mariosundays/SceneOptimizer) reports on both and launches them --
see [INTEGRATION.md](INTEGRATION.md) for the surface it reads from here.

Houdini 20.5+ | Windows, macOS, Linux | GPL-3.0

Menu: **Tools > Find Unused Assets**

![The main window](docs/screenshot-main.png)

Everything the open scene does not reference, why each one is safe to remove,
and what it costs on disk. Green rows are ticked; blue ones are used by another
scene and left alone. Right-click isolates a group -- one file type, one
folder, one reason:

## What it does

1. Walks every file parameter in the open scene to build the *used* set.
2. Walks the project folder on disk.
3. Anything on disk that nothing points at is an orphan.
4. You tick what you want; "Move to _unused" relocates it.

Step 1 covers the open scene only. To account for the **other** scenes in the
project, press **Scan other scenes** on the second tab -- see below.

Nothing is deleted. Files go to `<root>/_unused/`, keeping their folder
structure, and **Restore** puts them all back.

## The two tabs

### Unused files

The orphans, with a **Why** column saying how safe each one is to remove.
Only the first two are ticked for you:

| Why | Meaning | Ticked |
|---|---|---|
| `never referenced` | Nothing in the open scene points at it | yes |
| `backup file` | Named `_bak`, `_old`, `- Copy` and so on | yes |
| `older version` | A `_v001` where a `_v002` exists beside it | no |
| `partial sequence` | A frame outside the range the scene uses | no |
| `sidecar of used file` | A `.mtl` beside a used `.obj`, a `.tx` beside a used `.exr` | no |
| `used by other scene` | Another `.hip` in the project references it | no |
| `render output` | In a render or comp folder | no, and hidden by default |

Anything hinting that something else depends on the file stays unticked. You
can still tick it by hand -- the tool never blocks you, it just refuses to
volunteer.

### Other scenes

Press **Scan other scenes** to read every other `.hip` in the project. A
progress bar tracks it and Cancel stops it partway.

This does not run on its own, and it does not run on rescan. It reads each
scene whole -- around 50 MB/s -- which is nothing for a handful of files and
a visible stall on a project carrying years of versions. Making it a button
keeps the ordinary rescan instant.

Once it has run, any file a sibling scene references is marked `used by other
scene` on the first tab and unticked. The banner above the table tells you
which state you are in: **orange** until you have scanned, neutral after.

The table lists each scene, what it references, how much of that is inside the
project, and how many of its references are missing from disk. Select a scene
to list its files.

![The Other scenes tab](docs/screenshot-scenes.png)

91 scenes read here, and 1984 files that looked unused turned out to be
referenced by one of them.

### Paths built by expression

A File Cache node does not store its path -- it assembles one at cook time:

    `chs("basedir") + "/" + chs("basename")` + version + frame + filetype

With the scene **open** this is a non-issue: Houdini evaluates it and hands
back a real path. Reading a **closed** sibling scene is where it bites, because
all that is in the file is the backtick string. A scene can reference an entire
cache directory without one literal path appearing anywhere in it.

The folder is still recoverable -- `basedir` holds a plain `$HIP/geo` -- so the
scan collects directories as well as files, and anything inside one counts as
used by that scene. It protects too much rather than too little, which is the
right direction when the cost of being wrong is a re-sim.

This tab is what makes the first tab trustworthy, once you run it. A
`.hip` is a CPIO archive whose
payload is plain uncompressed text, so the paths a closed scene references can
be read without opening it -- no Houdini session, no waiting. `$HIP` and `$JOB`
are expanded against that scene's own folder, so a sibling using
`$HIP/tex/x.exr` resolves to the same file the open scene would see.

Right-click a row on the first tab and choose **Show scenes using this file**
to jump straight here.

## Render and comp output

A render is not an orphan. Nothing reads it back -- that is what an output
is -- so "nothing references this" says nothing about whether you still want
it. Left unhandled these bury everything else: one shot can put thousands of
frames in the list, every one of them ticked.

Output is found two ways, because neither alone is enough:

- **What the scene's ROPs write to.** `sopoutput`, `copoutput`, `vm_picture`,
  the Redshift and Arnold prefixes and so on. Exact, and it works whatever the
  folder is called -- but it only knows about the scene that is open.
- **Folder names.** `render`, `comp`, `frames`, `out`, `flipbook`, `preview`,
  `proxy` and their plurals, with order prefixes and versions allowed
  (`05_render`, `comp_v03`). This catches renders written by a scene that is
  not open, or no longer exists.

Matching is on whole path segments, so `compare/` and `rendering_notes/` are
not caught. Output words in the project root itself are ignored, or a project
living in `D:/renders/shot01` would call every one of its own files an output.

These are marked `render output`, **never ticked**, and hidden by default.
Untick **Hide render/comp** to see them -- clearing old renders is a real
thing to want, it just has to be deliberate.

## What is never touched

- **Non-asset files.** Only images, geometry and caches are ever considered.
  A `.txt`, `.py` or spreadsheet is left alone -- "no parameter points at it"
  is not evidence that a document is rubbish.
- **The `.hip` files themselves**, and anything in `_unused`, `backup`,
  `.git` or `tmp`.
- **Anything inside a folder a parameter names.** A File Cache in
  "Constructed" mode points its Base Folder at a directory and builds the
  filename itself, so nothing ever references those files by path. The whole
  folder is treated as in use.
- **Files the open scene uses**, including every frame of a sequence it
  resolves and both halves of a `$F`/`<UDIM>` pattern.

### Sequences and unresolved variables

Two cases are easy to get wrong, so they are handled explicitly:

- A scene pointing at **one explicit frame** (`fire.0001.exr` rather than
  `fire.$F4.exr`) still protects the rest of that sequence. The neighbours
  are listed as `partial sequence` and never ticked, so a live frame range
  cannot be swept up by "Select recommended".
- A path holding a variable Houdini only expands at cook time (`$HIPNAME`,
  `$OS`, `$SF` in a sim checkpoint) is **globbed** rather than treated as one
  unmatchable filename. Matching too many files is safe here; it can only mark
  something as still in use.

## Safety

By default the scan knows only the open scene. **A file another scene uses
will look unused until you press Scan other scenes** -- that is why the first
tab warns you in orange until you have. Beyond that:

- A path built by an **expression** at cook time may not be found by either
  method. Check the count on the Other scenes tab looks plausible before
  trusting a big selection.
- Every reference registers its **sequence stem**, so if a `$F` path resolves
  to nothing on disk -- wrong padding, frames not rendered yet -- the frames
  are still flagged `partial sequence` rather than called unused.
- If something you know is referenced still shows up, right-click it and pick
  **Why is this here?**. It prints the exact key the scan matched on and the
  referenced files in the same folder, which usually shows the mismatch.
- Scenes **outside** the project folder that reference files inside it are not
  seen at all.
- The move is reversible, so the recovery from a mistake is one button. That
  is deliberate: it is the reason the tool moves rather than deletes.

Run it on a copy of a project the first time.

## Sequences

A render folder holds thousands of frames, and one row each buries everything
else. Numbered frames are collapsed into a single row:

    beauty.[0001-0240].exr  (240 files)      render      689.4 MB

The row carries the whole sequence: its size is the total, its date is the
newest frame, and ticking it moves every frame. Hover the name to see the
individual files.

Compound extensions are handled, so `cache.0001.bgeo.sc` -- the standard
Houdini cache -- groups like anything else. Frames are only grouped when they
share a folder **and** an extension, so `cache.0001.bgeo` and
`cache.0001.exr` stay separate.

A sequence takes the **most cautious** reason of any frame in it. If one frame
of an otherwise unused sequence is referenced by another scene, the whole row
reads `used by other scene` and is not ticked -- because ticking it would move
that frame too. Such a row shows a partial tick.

Untick **Group sequences** to go back to one row per file.

## Table

- **Click a column heading** to sort. Size sorts by bytes and Modified by
  actual date, not as text.
- **Drag a divider** to resize, **double-click the header** to fit everything.
- **Double-click a row** to open the file in whatever app the OS associates
  with it -- the fastest way to decide whether a mystery cache matters.
- **Right-click** to move a single file, open it, copy its path, show it in
  Explorer, or isolate a group: one type, one folder, one reason.

## Notes

[Asset Consolidator's HOUDINI_NOTES.md](https://github.com/mariosundays/AssetConsolidator/blob/main/docs/HOUDINI_NOTES.md)
collects the scene-walking and Qt lessons behind both tools -- finding file
parameters by `stringType`, `raw` vs `resolved`, `commonpath` on Windows,
`exists` vs `isfile`, and the Qt table traps.

## Install

See [INSTALL.md](INSTALL.md). Short version: put the folder somewhere, point a
Houdini package `.json` at it, restart Houdini.

## Works with

Asset Cleaner stands alone, but [Scene Optimizer](https://github.com/mariosundays/SceneOptimizer) reports on
it alongside its companion tool and can launch it. That panel reads a
small, fixed set of functions from here -- see
[INTEGRATION.md](INTEGRATION.md) before renaming any of them.

## Tests

    python tests/run_all.py

No Houdini and no dependencies -- `hou` and PySide are stubbed. The move,
restore and `.hip` reading are tested against real files in a temp folder.

## Status

v1.1.0. Used on a real project, and most of what that turned up was the tool
being *too eager* -- caches and renders offered up that were plainly in use.
Those are fixed and covered by tests; see [CHANGELOG.md](CHANGELOG.md).

Still young. It moves rather than deletes precisely because of that, and
anything with a hint of a dependency is listed but never pre-ticked.

## Licence

GPL-3.0. See [LICENSE](LICENSE).
