# Integration

Asset Cleaner is **self-contained**. It has no dependencies on any other tool,
it installs on its own, and nothing here needs the notes below to work.

They matter for one reason: a third tool reads from this one, and it is not in
this repo.

| Tool | Job | Repo |
|---|---|---|
| **Asset Cleaner** | Finds what nothing uses and moves it out | this one |
| [Asset Consolidator](../AssetConsolidator) | Pulls outside files into the project | its own |
| [Scene Optimizer](../SceneOptimizer) | Reports on both and launches them | its own |

```
Asset Cleaner ─────┐
                   ├──>  Scene Optimizer      (reads only; never writes)
Asset Consolidator ┘
```

The dependency points one way. This tool knows nothing about Scene Optimizer
and never needs to -- but if you change one of the things below, that panel
stops reporting unused files correctly.

Building one of these?
[../AssetConsolidator/docs/HOUDINI_NOTES.md](../AssetConsolidator/docs/HOUDINI_NOTES.md)
has the scene-walking and Qt lessons, which apply to all three.

## What Scene Optimizer reads from this tool

| It calls | For |
|---|---|
| `scan(root, check_other_scenes=False)` | Its "Unused files" row. Always `False` -- reading sibling `.hip` files is slow and stays opt-in inside this tool |
| `unused_size(root)` | Its "Staged in _unused" row |
| `project_root()` | Resolving the project, rather than deciding it itself |
| `main()` | Its **Find Unused Assets...** button |
| `Orphan.size_bytes` | Totalling what could be reclaimed |
| `Orphan.selected` | Counting how many this tool would actually recommend |

That is the whole surface. Everything else here is private.

## `scan` returning a pair is part of the contract

`scan()` returns `(orphans, scenes)`. The panel unpacks both, so returning a
bare list -- the obvious "simplification" when the sibling scan is off and
`scenes` is always empty -- breaks it.

`check_other_scenes` defaults to `False` and should stay that way. The panel
passes it explicitly, but the default is what keeps an ordinary rescan fast:
reading every sibling `.hip` means reading each one whole.

## `Orphan.selected` means "recommended"

The panel counts it to say how many files this tool would actually offer to
move. It is a plain `bool` set in `__init__` from `reason in AUTO_SELECT`, and
the UI flips it as the user ticks rows.

Anything that hints another file or scene depends on an orphan must keep it
`False`: sidecars, older versions, partial sequences and files used by another
scene are all listed but never pre-ticked. That rule is what makes the count
meaningful rather than alarming.

## Changes that would break it

- Renaming `scan`, `unused_size`, `project_root` or `main`
- Dropping or renaming the `check_other_scenes` parameter
- Changing what `scan` returns -- the panel unpacks a 2-tuple
- Renaming `Orphan.size_bytes` or `.selected`, or turning either into a method

Adding things is always safe. Renaming and re-signaturing is what bites.

Note that `scene_references()` is **private** despite being the heart of the
scan: it returns a 4-tuple and has already grown from 3, so nothing outside
this repo should unpack it.

## How you find out

`SceneOptimizer/tests/test_contract.py` imports this module for real and checks
every item above. Run it from that repo after changing anything in the list:

    cd ../SceneOptimizer && python tests/run_all.py

It reports `32 checks passed` when all three repos sit side by side, and skips
cleanly when they do not -- so it is only meaningful from a working copy that
has all three, which is where a break would be introduced anyway.

This tool's own suite (`python tests/run_all.py` here) does not know Scene
Optimizer exists, and should stay that way.
