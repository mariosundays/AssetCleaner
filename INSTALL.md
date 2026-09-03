# Install

Asset Cleaner is a Houdini package. No build step, no dependencies beyond
Houdini itself.

## 1. Put the folder somewhere permanent

Anywhere you like, for example:

    C:\Users\<you>\Documents\houdini_tools\AssetCleaner

## 2. Point a package file at it

Houdini reads `.json` package files from a packages folder. If you already have
one (a `HOUDINI_PACKAGE_DIR` env var, or `Documents\houdini<ver>\packages`),
drop `asset_cleaner.json` in there and edit the two paths to match where
you put the folder:

    {
        "enable": "houdini_version >= '20.5'",
        "show": true,
        "process_order": 10,

        "hpath": [ "C:/path/to/AssetCleaner" ],

        "env": [
            {
                "PYTHONPATH": [
                    "C:/path/to/AssetCleaner/python",
                    { "method": "prepend" }
                ]
            }
        ]
    }

Forward slashes work fine on Windows and avoid escaping problems.

If you keep the package JSON *inside* the tool folder, you can use
`${HOUDINI_PACKAGE_PATH}` instead of hard-coding the path -- it resolves to the
folder holding the JSON.

## 3. Restart Houdini

The tool appears under **Tools > Find Unused Assets** on the main menu bar.

## Verifying

**Windows > Package Browser** lists the package and shows whether it loaded.
If the menu item is missing, that is the first place to look.

To debug path problems, set `HOUDINI_PACKAGE_VERBOSE=1` and launch Houdini from
a terminal -- it prints the resolved `HOUDINI_PATH`.

## Requirements

- Houdini 20.5 or newer (tested on 20.5 through 22.0)
- Windows, macOS or Linux. "Show in Explorer" is Windows-only; everything else
  is platform independent.
