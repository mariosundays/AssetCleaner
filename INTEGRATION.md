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

## What Scene Optimizer reads from this tool

| It calls | For |
|---|---|
| `scan(root, check_other_scenes=False)` | Its "Unused files" row. Always `False` -- the sibling-scene read stays opt-in in this tool's own UI, where there is a progress bar and a Cancel |
| `unused_size(root)` | Its "Staged in _unused" row |
| `project_root()` | Resolving the project, rather than deciding it itself |
| `main()` | Its **Find Unused Assets...** button |
| `Orphan.size_bytes` | Totalling reclaimable bytes |
| `Orphan.selected` | Counting how many orphans this tool would actually recommend, as opposed to merely list |

That is the whole surface. Everything else here is private.

## Changes that would break it

- Renaming `scan`, `unused_size`, `project_root` or `main`
- Dropping or renaming the `check_other_scenes` parameter, or changing its
  default in a way that makes the fast path slow
- Changing what `scan` returns -- the panel unpacks `(orphans, scenes)`
- Renaming `Orphan.size_bytes` or `Orphan.selected`, or making either
  something other than a number and a bool

Adding things is always safe. Renaming and re-signaturing is what bites.

## How you find out

`SceneOptimizer/tests/test_contract.py` imports this module for real and
checks every item above. Run it from that repo after changing anything in the
list:

    cd ../SceneOptimizer && python tests/run_all.py

It reports `32 checks passed` when all three repos sit side by side, and skips
cleanly when they do not -- so it is only meaningful from a working copy that
has all three, which is where a break would be introduced anyway.

This tool's own suite (`python tests/run_all.py` here) does not know Scene
Optimizer exists, and should stay that way.
