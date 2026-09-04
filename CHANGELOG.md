# Changelog

## 1.1.0 -- 2026-09-04

First round of use on a real project (3327 unused files, 6.1 GB). Everything
below came out of that, and most of it is about **not** offering files up for
deletion that are actually in use.

### Fixed -- files reported as unused that were not

- **`.bgeo.sc` frames.** The frame parser matched a single-dot extension, so
  every Houdini cache written as `name.0001.bgeo.sc` failed to parse. Those
  frames did not group into sequences and, worse, lost their partial-sequence
  protection -- so frames of a *referenced* cache were labelled
  `never referenced` and ticked.
- **File Cache folders.** A File Cache in "Constructed" mode points its Base
  Folder at a *directory* and builds the filename itself, so nothing ever
  references those files by path. The scan compared exact paths only, so every
  frame inside a live cache came back ticked. Anything under a referenced
  folder is now in use.
- **Sequences whose glob resolved nothing.** Wrong padding or an unrendered
  range meant no frame was protected. Every reference now registers its
  sequence stem whatever form it took.
- **Paths built by expression in *closed* scenes.** A File Cache assembles its
  path from other parameters, so reading a sibling `.hip` as text recovers a
  backtick string, not a path. Folders are now recovered alongside files, so a
  cache directory a sibling scene works in is protected.
- **References with no owning parameter**, which `hou.fileReferences()` reports
  as `(None, path)`, were being skipped.
- **Quoted or padded parameter values** failed to match the file on disk.

### Added

- **Render and comp output** gets its own verdict, is never ticked, and is
  hidden behind a **Hide render/comp** checkbox that is on by default. Nothing
  reads a render back -- that is what an output is -- so "unreferenced" says
  nothing about whether it is wanted, and thousands of frames buried the real
  orphans. Detected both from the scene's ROP parameters and from folder names
  (`render`, `comp`, `frames`, `out`, `flipbook`, ...).
- **Sequence grouping.** Numbered frames collapse to one row --
  `beauty.[0001-0240].exr  (240 files)`. A row takes the *most cautious*
  reason of any frame in it, so a sequence holding one protected frame is not
  ticked. **Group sequences** turns it off.
- **Why is this here?** on the right-click menu: prints the key the scan
  matched on, whether the file reads as part of a known sequence, and the
  referenced files in the same folder. For working out what a false positive
  actually missed.
- **Open with default app**, and double-click now opens the file rather than
  its folder.
- `INTEGRATION.md`, documenting the surface [Scene
  Optimizer](../SceneOptimizer) reads from this tool.

### Changed

- **The sibling-scene scan is now a button**, not something every rescan does.
  It reads each `.hip` whole, which is fine for a handful of scenes and a
  visible stall on a project with years of versions. Progress bar and Cancel.
- Long paths elide in the middle, keeping the filename visible.
- Rows carry their group object rather than an index, so sorting and
  regrouping cannot make a tick act on the wrong file.

### Performance

- **Startup, ~30s -> under a second.** The scene walk asked every parameter on
  every node for its `parmTemplate()`; `hou.fileReferences()` does it in one
  call and returns the expanded path too.
- **Version detection**, 3000 versioned files: 36.8s -> 0.039s. It rescanned
  the whole disk list per file; now it builds one index.
- **Folder recovery from sibling scenes**: 0.78s -> 0.022s per scene, by
  deduplicating candidates and filtering to the project before any `isdir()`.
  Each of those is a round trip on a Dropbox share.

### Tests

359 checks across 10 suites, up from 171. Still no Houdini or Qt needed.

## 1.0.0 -- 2026-09-03

First release. Walks the open scene, walks the project folder, and lists what
nothing references -- moved to `<root>/_unused/` rather than deleted, with
Restore. Second tab reads sibling `.hip` files off disk to flag files another
scene uses.
