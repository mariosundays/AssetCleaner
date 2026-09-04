# Houdini Asset Cleaner

Finds files in your project folder that nothing is using, and moves them out
of the way. Nothing is deleted.

Useful before archiving a shot or handing a project on, when the folder has
collected years of test caches and texture versions nobody can identify.

Houdini 20.5+ | Windows, macOS, Linux | GPL-3.0

Menu: **Tools > Find Unused Assets**

![The main window](docs/screenshot-main.png)

## How it works

1. Walks every file parameter in the open scene to find what is used.
2. Walks the project folder on disk.
3. Anything nothing points at is listed, with a reason.
4. Tick what you want and press **Move to _unused**.

Files go to `<root>/_unused/`, keeping their folder structure. **Restore** puts
them all back.

## The Why column

Only the first two are ticked for you:

| Why | Meaning | Ticked |
|---|---|---|
| `never referenced` | Nothing in the open scene points at it | yes |
| `backup file` | Named `_bak`, `_old`, `- Copy` | yes |
| `older version` | A `_v001` where a `_v002` exists beside it | no |
| `partial sequence` | A frame outside the range the scene uses | no |
| `sidecar of used file` | A `.mtl` beside a used `.obj` | no |
| `used by other scene` | Another `.hip` in the project uses it | no |
| `render output` | In a render or comp folder | no, hidden by default |

Anything suggesting something else depends on a file stays unticked. You can
still tick it by hand -- the tool never blocks you, it just will not volunteer.

## Sequences

Numbered frames collapse into one row:

    beauty.[0001-0240].exr  (240 files)     render     689.4 MB

Ticking the row moves every frame. Hover the name to see the files. Untick
**Group sequences** for one row per file.

## Render and comp output

A render is not an orphan -- nothing reads it back, so "unreferenced" says
nothing about whether you still want it. Files in `render`, `comp`, `frames`,
`out` and similar folders, and anywhere the scene's ROPs write, are marked
`render output` and **hidden by default**.

Untick **Hide render/comp** to see and clear them.

## Other scenes

The first tab only knows about the **open** scene, so a file another `.hip`
uses will look unused. Press **Scan other scenes** on the second tab to read
every other scene in the project -- without opening them -- and anything they
use is marked `used by other scene` and unticked.

![The Other scenes tab](docs/screenshot-scenes.png)

It is a button rather than automatic because it reads each scene whole, which
is slow on a project with years of versions.

## Table

- **Click a heading** to sort. Size sorts by bytes, Modified by date.
- **Double-click a row** to open the file.
- **Right-click** to move one file, open it, copy its path, show it in
  Explorer, or select a whole group: one type, one folder, one reason.
- **Why is this here?** on the right-click menu explains how a file was
  classified -- useful if something you know is used shows up.

## Install

A Houdini package. No build step, no dependencies beyond Houdini.

1. Put this folder somewhere permanent.
2. Copy `asset_cleaner.json` into your Houdini packages folder
   (`HOUDINI_PACKAGE_DIR`, or `Documents/houdini20.5/packages`) and edit the
   two paths in it to point at where you put the folder.
3. Restart Houdini.

Full details, including how to check it loaded, in [INSTALL.md](INSTALL.md).

## Safety

The scan knows what the open scene references, plus whatever the other-scenes
scan finds. It cannot see paths built by an expression at cook time in a scene
that is not open, or files a Python SOP reads at runtime.

So it moves rather than deletes, one button puts everything back, and anything
with a hint of a dependency is never ticked for you. Run it on a copy of a
project the first time.

## Works with

- [Asset Consolidator](https://github.com/mariosundays/AssetConsolidator) --
  the opposite job: pulls outside files *into* the project
- [Scene Optimizer](https://github.com/mariosundays/SceneOptimizer) --
  reports on both and launches them

## Tests

    python tests/run_all.py

359 checks, no Houdini or dependencies needed.

## Licence

GPL-3.0. See [LICENSE](LICENSE). Changes in [CHANGELOG.md](CHANGELOG.md).
