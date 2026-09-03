# Asset Cleaner -- find unused files in a Houdini project and set them aside.
# Copyright (C) 2026 Mario Domingos
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program. If not, see <https://www.gnu.org/licenses/>.

"""
Asset Cleaner -- the inverse of Asset Consolidator.

The consolidator walks parameters and asks "does this reference live outside
the project?". This walks the project folder on disk and asks the opposite:
"is anything still using this file?". What nothing uses is an orphan, and can
be moved into <root>/_unused/ where it is out of the way but recoverable.

Two tabs:

  Unused files   what the open scene does not reference.
  Other scenes   which OTHER .hip files in the project reference which files,
                 read straight off disk without opening them.

Works in Houdini 20.5 through 22.x (PySide2 and PySide6 both handled).

Menu entry: Tools > Find Unused Assets
"""

import os
import re
import shutil
import sys
import time

import hou

VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Qt compatibility -- H20.5 ships PySide2, H21+ ships PySide6.
# ---------------------------------------------------------------------------

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt
except ImportError:  # Houdini 20.5
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt


# ---------------------------------------------------------------------------
# What counts as a project asset
# ---------------------------------------------------------------------------

# Only these are ever considered for removal. Anything else in the project --
# a .txt, a .py, a spreadsheet -- is left alone entirely, because "nothing in
# the scene points at it" is not evidence that a document is rubbish.
ASSET_EXTS = {
    # images / textures
    ".exr", ".hdr", ".hdri", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
    ".tga", ".bmp", ".dpx", ".cin", ".rat", ".tx", ".psd", ".pic",
    # geometry / caches
    ".bgeo", ".bgeo.sc", ".geo", ".vdb", ".obj", ".fbx", ".ply", ".stl",
    ".usd", ".usda", ".usdc", ".usdz", ".sim", ".bclip", ".abc",
}

# Never walked into. Backups and the recycling folder we ourselves create.
SKIP_DIRS = {
    "_unused", "backup", ".git", ".svn", "__pycache__", "$recycle.bin",
    "tmp", "temp",
}

# Scene files, which are the *readers* of assets and never the orphans.
HIP_EXTS = (".hip", ".hiplc", ".hipnc", ".hip.bak")

# Sidecars -- a file that belongs to another file rather than standing alone.
# If the owner is used, the sidecar is used too, even though no parameter
# names it directly.
SIDECAR_OWNERS = {
    ".mtl": (".obj",),
    ".tx": (".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga"),
    ".rat": (".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga"),
    ".usdc": (".usd", ".usda"),
}

COMPOUND_EXTS = (".bgeo.sc", ".bgeo.gz", ".geo.gz", ".vdb.sc")

# Parameters that name a file but which we never want to treat as a reference.
SKIP_PARM_NAMES = {"hda_path", "otl_path"}

UNUSED_FOLDER = "_unused"


def _clean(path):
    """Normalise a path for comparison: forward slashes, no trailing slash."""
    if not path:
        return ""
    path = os.path.normpath(os.path.expandvars(path)).replace("\\", "/")
    return path.rstrip("/")


def _key(path):
    """The case-insensitive identity of a path, for set membership."""
    return _clean(path).lower()


def file_ext(filepath):
    """
    The extension of a path, lower case, with the dot. Compound suffixes are
    kept whole so a cache reads ".bgeo.sc" rather than ".sc".
    """
    name = os.path.basename((filepath or "").replace("\\", "/")).lower()
    for compound in COMPOUND_EXTS:
        if name.endswith(compound):
            return compound
    return os.path.splitext(name)[1]


def ext_label(filepath):
    """Upper-case label for the Type column, e.g. EXR, JPG, BGEO.SC."""
    ext = file_ext(filepath).lstrip(".")
    return ext.upper() if ext else "-"


# Distinct colour per extension, matching Asset Consolidator so the two tools
# read the same way side by side.
EXT_COLOURS = {
    "exr": "#7ee787", "hdr": "#7ee787", "hdri": "#7ee787",
    "png": "#6bb3ff", "jpg": "#6bb3ff", "jpeg": "#6bb3ff",
    "tif": "#5fd7d7", "tiff": "#5fd7d7", "tga": "#5fd7d7",
    "tx": "#a5d6a7", "rat": "#a5d6a7", "psd": "#c5a3ff",
    "abc": "#d2a8ff", "usd": "#d2a8ff", "usda": "#d2a8ff",
    "usdc": "#d2a8ff", "usdz": "#d2a8ff",
    "bgeo": "#ffb86b", "bgeo.sc": "#ffb86b", "geo": "#ffb86b",
    "vdb": "#ff9ec4", "obj": "#e3d16b", "fbx": "#e3d16b",
}

DEFAULT_EXT_COLOUR = "#9aa0a6"


def ext_colour(label):
    """Colour for an extension label as shown in the Type column."""
    return EXT_COLOURS.get((label or "").lower(), DEFAULT_EXT_COLOUR)


def _human(size):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return "{:.0f} {}".format(size, unit) if unit == "B" \
                else "{:.1f} {}".format(size, unit)
        size /= 1024.0
    return "{:.1f} PB".format(size)


def _age(mtime):
    """Human age of a timestamp: '3 days', '2 months'."""
    if not mtime:
        return "-"
    seconds = max(0, time.time() - mtime)
    for limit, div, name in ((90000, 3600, "hour"),
                             (2592000, 86400, "day"),
                             (31536000, 2592000, "month")):
        if seconds < limit:
            n = int(seconds // div)
            return "{} {}{}".format(n, name, "" if n == 1 else "s")
    n = int(seconds // 31536000)
    return "{} year{}".format(n, "" if n == 1 else "s")


# ---------------------------------------------------------------------------
# Project root resolution -- identical rules to Asset Consolidator, so the
# two tools always agree on where the project is.
# ---------------------------------------------------------------------------

def project_root():
    """
    Resolve the project root: the folder holding the current .hip file.

    $HIP is preferred over $JOB because Houdini always defines it and it is
    always correct for the open scene. $JOB is used instead when it is set to
    something real AND the .hip lives underneath it.
    """
    hip = _clean(hou.getenv("HIP") or "")
    job = _clean(hou.getenv("JOB") or "")

    if job and os.path.isdir(job):
        default_job = _clean(os.path.join(
            os.path.expanduser("~"), "houdini_projects"))
        if job.lower() != default_job.lower() and hip and is_inside(hip, job):
            return job

    return hip or job


def is_inside(filepath, root):
    """True when filepath lives under root."""
    if not root:
        return False
    filepath = _clean(filepath)
    root = _clean(root)
    if not filepath:
        return False
    try:
        common = os.path.commonpath([filepath.lower(), root.lower()])
        return common.replace("\\", "/").rstrip("/") == root.lower()
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Sequence handling -- $F, $F4, %04d, ####, <UDIM>
# ---------------------------------------------------------------------------

SEQ_PATTERNS = [
    re.compile(r"\$F\d*", re.IGNORECASE),
    re.compile(r"%0?\d*d"),
    re.compile(r"#+"),
    re.compile(r"<UDIM>", re.IGNORECASE),
]


def is_sequence(path):
    return any(p.search(path) for p in SEQ_PATTERNS)


def sequence_glob(path):
    """Turn a sequence path into a glob so we can find every frame on disk."""
    import glob as _glob

    pattern = path
    for p in SEQ_PATTERNS:
        pattern = p.sub("*", pattern)
    pattern = re.sub(r"\*+", "*", pattern)
    try:
        return sorted(_glob.glob(pattern))
    except Exception:
        return []


# Any Houdini variable still sitting in a path after $HIP/$JOB are expanded:
# $HIPNAME, $OS, $SF, ${FOO}. We cannot evaluate these outside a session, so
# the path becomes a glob instead of being thrown away.
VARIABLE_RE = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")


def expand_glob(path):
    """
    Every file on disk a path could name, once sequence tokens and leftover
    variables are turned into wildcards.

    Used for references we cannot resolve exactly. Matching too many files is
    safe here -- it can only mark something as still in use -- while matching
    too few would offer a live cache up for deletion.
    """
    import glob as _glob

    pattern = path
    for p in SEQ_PATTERNS:
        pattern = p.sub("*", pattern)
    pattern = VARIABLE_RE.sub("*", pattern)
    pattern = re.sub(r"\*+", "*", pattern)

    # A pattern that lost its directory to a wildcard would walk far too much.
    if pattern.startswith("*"):
        return []
    try:
        return _glob.glob(pattern)
    except Exception:
        return []


def sequence_stem(path):
    """
    The directory + literal prefix of a sequence, used to group frames.
    'C:/p/tex/fire.$F4.exr' -> 'c:/p/tex/fire.'
    """
    path = _clean(path).lower()
    for p in SEQ_PATTERNS:
        m = p.search(path)
        if m:
            return path[:m.start()]
    return path


# A frame number at the end of a name, before the extension. The extension is
# stripped by file_ext() first rather than matched here, so compound suffixes
# like .bgeo.sc work -- matching "\.[^.]+$" instead would fail on every
# Houdini cache written as name.0001.bgeo.sc.
FRAME_RE = re.compile(r"^(?P<stem>.*?)(?P<frame>\d{3,8})$")


def split_frame(path):
    """
    Split a filename into (folder, stem, frame number, padding, extension).

    Returns None when the name does not end in a frame number.

        'C:/p/geo/cache.0007.bgeo.sc'
            -> ('c:/p/geo', 'cache.', 7, 4, '.bgeo.sc')

    One parser for every caller, because the frame rules have to agree: what
    groups into a sequence row and what counts as protecting its neighbours
    must be the same question.
    """
    key = _key(path)
    folder, name = os.path.split(key)

    ext = file_ext(name)
    if not ext:
        return None
    base = name[:-len(ext)]

    match = FRAME_RE.match(base)
    if not match:
        return None

    frame = match.group("frame")
    return folder, match.group("stem"), int(frame), len(frame), ext


def frame_stem(path):
    """
    The stem of a numbered frame, or None when the name is not one.

    'C:/p/tex/fire.0007.exr' -> 'c:/p/tex/fire.'

    This exists because a scene often points at ONE explicit frame rather than
    a $F pattern. Without it the other frames of that sequence look like
    unrelated files and would be ticked for removal -- which is how a tool
    like this quietly eats a cache.
    """
    parts = split_frame(path)
    if parts is None:
        return None
    folder, stem, _frame, _width, _ext = parts
    return "{}/{}".format(folder, stem)


# ---------------------------------------------------------------------------
# The referenced set -- what the OPEN scene uses
# ---------------------------------------------------------------------------

def _iter_file_parms():
    """
    Yield every file-typed parameter in the scene.

    hou.fileReferences() does this in one C++ call. The obvious alternative --
    walking allSubChildren() and asking each parm for its parmTemplate() --
    builds a Python object for every parameter on every node, which on a real
    scene is tens of thousands of crossings and takes tens of seconds. This
    returns in well under one.

    Yields (parm, resolved_path) pairs. The path comes back already expanded,
    so the caller does not have to eval() the parameter again. resolved is
    None on the fallback path, meaning "work it out yourself".
    """
    try:
        references = hou.fileReferences()
    except Exception:
        references = None

    if references is not None:
        for parm, path in references:
            # parm is None for a reference that belongs to no parameter --
            # a $HIP-relative path Houdini tracks itself, for instance. It
            # is still a real reference, so it must still protect its file;
            # dropping it is how a used file gets called never referenced.
            if parm is None:
                if path:
                    yield None, path
                continue
            try:
                if parm.name() in SKIP_PARM_NAMES:
                    continue
            except Exception:
                continue
            yield parm, path
        return

    # Fallback for anything that does not expose fileReferences(). Slow, but
    # only reached if the fast path is unavailable.
    for node in hou.node("/").allSubChildren(top_down=True,
                                             recurse_in_locked_nodes=False):
        try:
            parms = node.parms()
        except hou.OperationFailed:
            continue

        for parm in parms:
            try:
                template = parm.parmTemplate()
            except Exception:
                continue

            if not isinstance(template, hou.StringParmTemplate):
                continue
            if template.stringType() != hou.stringParmType.FileReference:
                continue
            if parm.name() in SKIP_PARM_NAMES:
                continue
            yield parm, None


def scene_references():
    """
    Every file the open scene points at, as a set of lower-case paths, plus
    the sequence stems it uses.

    Returns (paths, stems, by_path) where by_path maps a path to the list of
    node paths referencing it -- that is what the "Used by" column shows.
    """
    paths = set()
    stems = set()
    by_path = {}

    for parm, supplied in _iter_file_parms():
        # fileReferences() hands back the expanded path already, so only fall
        # back to eval() when we came in through the slow path.
        resolved = supplied
        if resolved is None:
            if parm is None:
                continue
            try:
                resolved = parm.eval()
            except Exception:
                continue

        if not resolved or not resolved.strip():
            continue

        # A parameter can carry surrounding quotes or stray whitespace; both
        # would make an otherwise identical path fail to match the disk walk.
        resolved = resolved.strip().strip('"').strip("'").strip()
        resolved = _clean(resolved)
        if resolved.startswith(("op:", "http:", "https:", "opdef:")):
            continue
        if not os.path.isabs(resolved):
            continue

        # Only paid for references we actually keep, and only to label the
        # "used by" tooltip -- never to decide whether a file is in use.
        try:
            node_path = parm.node().path() if parm is not None else "(scene)"
        except Exception:
            node_path = "?"

        # eval() resolves most things, but a parameter can still come back
        # holding a variable Houdini only expands at cook time. Glob those
        # rather than treating them as one literal, unmatchable filename.
        if is_sequence(resolved) or VARIABLE_RE.search(resolved):
            for frame in expand_glob(resolved):
                k = _key(frame)
                paths.add(k)
                by_path.setdefault(k, []).append(node_path)
        else:
            k = _key(resolved)
            paths.add(k)
            by_path.setdefault(k, []).append(node_path)

        # Register the sequence stem for EVERY reference, whatever form it
        # took. This is the safety net: if the glob above resolved nothing --
        # wrong padding, frames not rendered yet, a token we cannot expand --
        # the stem still marks the whole sequence as spoken for, so its
        # frames are flagged rather than offered up as never referenced.
        stem = (sequence_stem(resolved) if is_sequence(resolved)
                else frame_stem(resolved))
        if stem:
            stems.add(stem)

    return paths, stems, by_path


# ---------------------------------------------------------------------------
# Reading OTHER .hip files without opening them
#
# A .hip is a CPIO archive whose payload is plain hscript text -- not
# compressed -- so the paths a closed scene references can be pulled straight
# out with a string scan. That is what feeds the "Other scenes" tab.
# ---------------------------------------------------------------------------

# Printable runs inside the binary. Paths never span one of these.
_PRINTABLE = re.compile(rb"[ -~]{6,400}")

# A path-looking token ending in an extension we care about. Deliberately
# broad on the leading form: absolute, $HIP/$JOB-relative, or UNC.
_PATH_TOKEN = re.compile(
    rb"(?:[A-Za-z]:[/\\]|\$HIP[/\\]|\$JOB[/\\]|//)"
    rb"[^\s\"'<>|*\?,;=\)\(\]\[]{2,180}"
    rb"\.(?:exr|hdr|hdri|png|jpe?g|tiff?|tga|bmp|dpx|cin|rat|tx|psd|pic"
    rb"|bgeo\.sc|bgeo|geo|vdb|obj|fbx|ply|stl|usd[acz]?|sim|bclip|abc)\b",
    re.IGNORECASE)


def paths_in_hip(hip_path, hip_dir=None, job=None):
    """
    Extract every asset path a .hip file references, without opening it.

    $HIP and $JOB are expanded against the scene's own folder, so a sibling
    scene using "$HIP/tex/x.exr" resolves to the same file the open scene
    would see. Returns a set of lower-case absolute paths.

    Paths are read out of the raw file, so this reports what the scene *says*
    it uses, including references that no longer resolve on disk. That is the
    right side to err on for a tool that deletes things.

    Any other variable left in the path ($HIPNAME, $OS, $SF in a sim
    checkpoint) is globbed, because a path we cannot resolve exactly must
    still be allowed to match the files it might name -- otherwise a cache
    that IS in use looks unused.
    """
    hip_dir = _clean(hip_dir or os.path.dirname(hip_path))
    job = _clean(job or hip_dir)

    try:
        with open(hip_path, "rb") as handle:
            data = handle.read()
    except (OSError, IOError):
        return set()

    found = set()
    for run in _PRINTABLE.findall(data):
        for match in _PATH_TOKEN.findall(run):
            text = match.decode("utf-8", "replace").replace("\\", "/")

            # Expand the two tokens we can resolve ourselves.
            if text.lower().startswith("$hip/"):
                text = hip_dir + "/" + text[5:]
            elif text.lower().startswith("$job/"):
                text = job + "/" + text[5:]

            if is_sequence(text) or VARIABLE_RE.search(text):
                for frame in expand_glob(text):
                    found.add(_key(frame))
                # Keep the unresolved form too, so the scene's own reference
                # count still reflects what it asks for.
                found.add(_key(text))
            else:
                found.add(_key(text))

    return found


def find_sibling_hips(root, exclude=None):
    """Every .hip in the project other than the open one, newest first."""
    exclude = _key(exclude or "")
    hips = []
    for folder, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for name in filenames:
            if not name.lower().endswith(HIP_EXTS):
                continue
            full = _clean(os.path.join(folder, name))
            if _key(full) == exclude:
                continue
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                mtime = 0
            hips.append((mtime, full))
    hips.sort(reverse=True)
    return [path for _mtime, path in hips]


def scan_other_scenes(root, exclude=None, progress=None):
    """
    Read every sibling .hip and report what each one references.

    Returns (scenes, used_by) where scenes is a list of SceneRef and used_by
    maps a lower-case asset path to the list of scene paths using it.
    """
    root = _clean(root)
    scenes = []
    used_by = {}

    hips = find_sibling_hips(root, exclude)
    for index, hip in enumerate(hips):
        if progress is not None and not progress(index, len(hips), hip):
            break

        paths = paths_in_hip(hip, os.path.dirname(hip), root)
        inside = {p for p in paths if is_inside(p, root)}
        scenes.append(SceneRef(hip, paths, inside))
        for path in paths:
            used_by.setdefault(path, []).append(hip)

    return scenes, used_by


class SceneRef(object):
    """One sibling .hip file and the assets it references."""

    def __init__(self, path, all_paths, inside_paths):
        self.path = path
        self.all_paths = all_paths
        self.inside_paths = inside_paths

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def folder(self):
        return os.path.dirname(self.path)

    @property
    def mtime(self):
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0

    @property
    def missing(self):
        """References that are not on disk -- a broken link in that scene."""
        return {p for p in self.all_paths if not os.path.exists(p)}


# ---------------------------------------------------------------------------
# Confidence -- how safe is it to move this file out
# ---------------------------------------------------------------------------

SAFE_NEVER = "never referenced"
SAFE_BACKUP = "backup file"
SAFE_VERSION = "older version"
SAFE_SIDECAR = "sidecar of used file"
SAFE_OTHER_SCENE = "used by other scene"
SAFE_PARTIAL_SEQ = "partial sequence"

# Names that are self-evidently disposable regardless of references.
BACKUP_HINTS = ("_bak", ".bak", "_backup", "_old", "_tmp", "_temp",
                ".autosave", "_copy", " - copy")

VERSION_RE = re.compile(r"[._-]v(\d{2,4})\b", re.IGNORECASE)

CONFIDENCE_HELP = {
    SAFE_NEVER:
        "Nothing in the open scene points at this file.\n"
        "Safe to set aside, unless another scene uses it.",
    SAFE_BACKUP:
        "The name marks this as a backup or temporary copy.\n"
        "Usually safe to remove even if something references it.",
    SAFE_VERSION:
        "An older version of a file that also exists at a higher version.\n"
        "Kept out of the default selection -- versions are often kept "
        "deliberately.",
    SAFE_SIDECAR:
        "This belongs to a file the scene does use, such as a .mtl beside\n"
        "a used .obj. Removing it can break the file that needs it.",
    SAFE_OTHER_SCENE:
        "Another .hip in this project references this file.\n"
        "See the 'Other scenes' tab. Never selected automatically.",
    SAFE_PARTIAL_SEQ:
        "Part of a sequence the scene uses, but this frame is outside the\n"
        "referenced range. Never selected automatically.",
}

CONFIDENCE_COLOURS = {
    SAFE_NEVER: "#7ee787",
    SAFE_BACKUP: "#7ee787",
    SAFE_VERSION: "#ffb86b",
    SAFE_SIDECAR: "#ff9ec4",
    SAFE_OTHER_SCENE: "#6bb3ff",
    SAFE_PARTIAL_SEQ: "#ffb86b",
}

# Which reasons are ticked by default. Anything that hints another file or
# scene depends on it stays unticked -- the user can still tick it by hand.
AUTO_SELECT = {SAFE_NEVER, SAFE_BACKUP}


def is_backup_name(path):
    lower = os.path.basename(_clean(path)).lower()
    return any(hint in lower for hint in BACKUP_HINTS)


def version_of(path):
    """The version number in a filename, or None."""
    match = VERSION_RE.search(os.path.basename(_clean(path)))
    return int(match.group(1)) if match else None


def version_stem(path):
    """The filename with its version token removed, for grouping versions."""
    name = os.path.basename(_clean(path)).lower()
    return VERSION_RE.sub("", name)


# ---------------------------------------------------------------------------
# Scanning the project folder
# ---------------------------------------------------------------------------

class Orphan(object):
    """One file on disk that the open scene does not reference."""

    def __init__(self, path, root, reason):
        self.path = _clean(path)
        self.root = _clean(root)
        self.reason = reason
        self.other_scenes = []      # SceneRef paths using it, filled in later
        self.error = ""
        self.moved_to = ""          # where it actually landed, after a move
        self.selected = reason in AUTO_SELECT

        try:
            stat = os.stat(self.path)
            self.size_bytes = stat.st_size
            self.mtime = stat.st_mtime
        except OSError:
            self.size_bytes = 0
            self.mtime = 0

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def relative(self):
        """Path relative to the project root, for display and for the move."""
        if is_inside(self.path, self.root):
            return self.path[len(self.root):].lstrip("/")
        return self.name

    @property
    def folder(self):
        rel = self.relative
        parent = os.path.dirname(rel)
        return parent or "."

    @property
    def ext_label(self):
        return ext_label(self.path)

    @property
    def age(self):
        return _age(self.mtime)

    @property
    def dest(self):
        """Where it goes: <root>/_unused/<same relative path>."""
        return "{}/{}/{}".format(self.root, UNUSED_FOLDER, self.relative)


# ---------------------------------------------------------------------------
# Grouping -- one row per sequence instead of one row per frame
#
# A render folder holds thousands of frames. Listed one per row they bury
# everything else and make the table useless. A group is purely a display
# and selection convenience: the Orphan objects underneath are still what
# gets moved, so nothing about the move or restore changes.
# ---------------------------------------------------------------------------

class Group(object):
    """
    One row in the table: either a single file or a whole sequence.

    Presents the same interface the table reads off an Orphan -- name, size,
    reason, folder -- so the UI does not care which it is looking at.
    """

    def __init__(self, orphans, stem=None):
        self.orphans = list(orphans)
        self.stem = stem
        first = self.orphans[0]
        self.root = first.root
        self.folder = first.folder
        self.ext_label = first.ext_label

    # -- what the table shows ---------------------------------------------

    @property
    def is_sequence(self):
        return len(self.orphans) > 1

    @property
    def count(self):
        return len(self.orphans)

    @property
    def name(self):
        """'beauty.[0001-0240].exr  (240 files)' for a sequence."""
        if not self.is_sequence:
            return self.orphans[0].name
        frames = sorted(f for f in (frame_number(o.path) for o in self.orphans)
                        if f is not None)
        base = os.path.basename(self.stem or "")
        ext = file_ext(self.orphans[0].path)
        if frames:
            span = ("{:0{w}d}-{:0{w}d}".format(
                frames[0], frames[-1], w=frame_width(self.orphans[0].path)))
        else:
            span = "..."
        return "{}[{}]{}  ({} files)".format(base, span, ext, self.count)

    @property
    def size_bytes(self):
        return sum(o.size_bytes for o in self.orphans)

    @property
    def mtime(self):
        """The newest frame -- a sequence is as recent as its last write."""
        return max((o.mtime for o in self.orphans), default=0)

    @property
    def age(self):
        return _age(self.mtime)

    @property
    def path(self):
        """A representative path, for Copy path and Show in Explorer."""
        return self.orphans[0].path

    @property
    def reason(self):
        """
        The most cautious reason in the group.

        If any frame is protected the whole row says so, because ticking the
        row moves every frame in it.
        """
        for reason in (SAFE_OTHER_SCENE, SAFE_PARTIAL_SEQ, SAFE_SIDECAR,
                       SAFE_VERSION, SAFE_NEVER, SAFE_BACKUP):
            if any(o.reason == reason for o in self.orphans):
                return reason
        return self.orphans[0].reason

    @property
    def other_scenes(self):
        seen = []
        for orphan in self.orphans:
            for scene in orphan.other_scenes:
                if scene not in seen:
                    seen.append(scene)
        return seen

    # -- selection ---------------------------------------------------------

    @property
    def selected(self):
        return all(o.selected for o in self.orphans)

    @selected.setter
    def selected(self, state):
        for orphan in self.orphans:
            orphan.selected = state

    @property
    def partially_selected(self):
        picked = [o for o in self.orphans if o.selected]
        return 0 < len(picked) < len(self.orphans)


def frame_number(path):
    """The frame number in a filename, or None."""
    parts = split_frame(path)
    return parts[2] if parts else None


def frame_width(path):
    """How many digits the frame number is padded to."""
    parts = split_frame(path)
    return parts[3] if parts else 4


def group_orphans(orphans, enabled=True):
    """
    Collapse runs of numbered frames into one row each.

    Files that are not part of a sequence come back as groups of one, so the
    table only ever deals in groups. Order is preserved: a group appears
    where its first frame did.
    """
    if not enabled:
        return [Group([o]) for o in orphans]

    groups = []
    by_stem = {}

    for orphan in orphans:
        stem = frame_stem(orphan.path)
        # Only group when the frames share a folder AND an extension --
        # "cache.001.bgeo" and "cache.001.exr" are not one sequence.
        key = None if stem is None else (stem, file_ext(orphan.path))

        if key is None:
            groups.append(Group([orphan]))
            continue

        existing = by_stem.get(key)
        if existing is None:
            group = Group([orphan], stem=stem)
            by_stem[key] = group
            groups.append(group)
        else:
            existing.orphans.append(orphan)

    return groups


def walk_project(root):
    """Every asset file under the project root, skipping the noise folders."""
    root = _clean(root)
    out = []
    for folder, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for name in filenames:
            full = _clean(os.path.join(folder, name))
            if file_ext(full) in ASSET_EXTS:
                out.append(full)
    return out


def version_index(paths):
    """
    Map (folder, versionless name) -> the highest version number seen there.

    Built once per scan. Without it, deciding whether a _v001 is superseded
    means rescanning the whole disk list for every versioned file, which is
    quadratic and noticeable on a big texture library.
    """
    index = {}
    for path in paths:
        version = version_of(path)
        if version is None:
            continue
        key = _key(path)
        group = (os.path.dirname(key), version_stem(path))
        if version > index.get(group, -1):
            index[group] = version
    return index


def classify_orphan(path, used_paths, used_stems, all_on_disk):
    """
    Decide whether a file is an orphan and, if so, how safe it is to move.

    Returns a reason string, or None when the file is genuinely in use.
    """
    key = _key(path)

    if key in used_paths:
        return None

    # A frame sitting in a sequence the scene uses, but outside the range it
    # actually resolved. Flag rather than hide -- but never auto-tick.
    #
    # Matching on the stem alone would catch "fire_render.exr" under the stem
    # "fire_", so the rest of the name has to actually be a frame number.
    own_stem = frame_stem(key)
    if own_stem is not None and own_stem in used_stems:
        return SAFE_PARTIAL_SEQ

    # Backups are disposable whatever else is true, so this outranks the
    # sidecar and version checks below.
    if is_backup_name(path):
        return SAFE_BACKUP

    # A sidecar whose owner is in use travels with its owner.
    ext = file_ext(path)
    owners = SIDECAR_OWNERS.get(ext)
    if owners:
        base = os.path.splitext(_key(path))[0]
        for owner_ext in owners:
            if (base + owner_ext) in used_paths:
                return SAFE_SIDECAR

    # An older version of something that also exists at a higher version.
    #
    # all_on_disk may be the prebuilt index from version_index(); fall back to
    # building one for a bare list so the function still works standalone.
    version = version_of(path)
    if version is not None:
        index = (all_on_disk if isinstance(all_on_disk, dict)
                 else version_index(all_on_disk))
        highest = index.get((os.path.dirname(key), version_stem(path)))
        if highest is not None and highest > version:
            return SAFE_VERSION

    return SAFE_NEVER


def apply_other_scenes(orphans, used_by):
    """
    Downgrade every orphan that a sibling scene turns out to be using.

    Kept separate from scan() because reading the other scenes is opt-in --
    it reads whole .hip files off disk, so on a big project it is slow enough
    to be worth asking for rather than doing on every rescan. This is what
    the "Other scenes" tab runs once its scan finishes.

    Returns the number of orphans that changed.
    """
    changed = 0
    for orphan in orphans:
        users = used_by.get(_key(orphan.path))
        if not users:
            continue
        orphan.other_scenes = users
        # A backup stays a backup: the name is better evidence than a
        # reference, and it should still be offered for removal.
        if orphan.reason != SAFE_BACKUP:
            orphan.reason = SAFE_OTHER_SCENE
            orphan.selected = False
        changed += 1
    return changed


def scan(root=None, check_other_scenes=False, progress=None):
    """
    Find every asset in the project the open scene does not reference.

    Only the open scene is walked by default. Reading the other .hip files in
    the project is opt-in via check_other_scenes, because it reads them whole
    off disk -- fine for a handful of scenes, slow for a project with years of
    versions in it.

    Returns (orphans, scenes) -- scenes is empty unless the sibling scan ran.
    """
    root = _clean(root or project_root())
    if not root or not os.path.isdir(root):
        return [], []

    used_paths, used_stems, _by_path = scene_references()
    on_disk = walk_project(root)

    versions = version_index(on_disk)

    orphans = []
    for path in on_disk:
        reason = classify_orphan(path, used_paths, used_stems, versions)
        if reason is not None:
            orphans.append(Orphan(path, root, reason))

    orphans.sort(key=lambda o: (o.folder, o.name))

    scenes = []
    if check_other_scenes:
        try:
            current = hou.hipFile.path()
        except Exception:
            current = ""
        scenes, used_by = scan_other_scenes(root, current, progress)
        apply_other_scenes(orphans, used_by)

    return orphans, scenes


# ---------------------------------------------------------------------------
# Moving files out -- and putting them back
# ---------------------------------------------------------------------------

def _unique_dest(dest):
    """Never overwrite something already sitting in _unused."""
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(dest)
    for i in range(1, 1000):
        candidate = "{}_{}{}".format(stem, i, ext)
        if not os.path.exists(candidate):
            return candidate
    return dest


def move_out(orphans, progress=None):
    """
    Move each orphan into <root>/_unused/, preserving its relative folder
    structure so the move can be undone by hand or with restore().

    Returns (moved, freed_bytes, errors).
    """
    moved = 0
    freed = 0
    errors = []

    total = len(orphans)
    for index, orphan in enumerate(orphans):
        if progress is not None:
            if not progress(index, total, orphan):
                errors.append("Cancelled by user.")
                break

        dest = orphan.dest
        dest_dir = os.path.dirname(dest)

        try:
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir)
        except OSError as exc:
            errors.append("{}  cannot create {}: {}".format(
                orphan.name, dest_dir, exc))
            continue

        try:
            size = orphan.size_bytes
            dest = _unique_dest(dest)
            shutil.move(orphan.path, dest)
            orphan.moved_to = dest
            moved += 1
            freed += size
        except (OSError, IOError) as exc:
            orphan.error = str(exc)
            errors.append("{}  move failed: {}".format(orphan.name, exc))

    return moved, freed, errors


def restore(root, progress=None):
    """
    Put everything in <root>/_unused/ back where it came from.

    The mirror of move_out: the relative path under _unused is exactly the
    relative path under the project, which is what makes this possible.
    Returns (restored, errors).
    """
    root = _clean(root)
    unused = "{}/{}".format(root, UNUSED_FOLDER)
    if not os.path.isdir(unused):
        return 0, ["Nothing to restore -- no {} folder.".format(UNUSED_FOLDER)]

    items = []
    for folder, _dirnames, filenames in os.walk(unused):
        for name in filenames:
            items.append(_clean(os.path.join(folder, name)))

    restored = 0
    errors = []
    for index, source in enumerate(items):
        if progress is not None:
            if not progress(index, len(items), source):
                errors.append("Cancelled by user.")
                break

        relative = source[len(unused):].lstrip("/")
        dest = "{}/{}".format(root, relative)
        try:
            dest_dir = os.path.dirname(dest)
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir)
            if os.path.exists(dest):
                errors.append("{}  already back in place, left alone".format(
                    relative))
                continue
            shutil.move(source, dest)
            restored += 1
        except (OSError, IOError) as exc:
            errors.append("{}  restore failed: {}".format(relative, exc))

    # Clean up the empty skeleton we leave behind.
    for folder, dirnames, filenames in os.walk(unused, topdown=False):
        if not dirnames and not filenames:
            try:
                os.rmdir(folder)
            except OSError:
                pass

    return restored, errors


def unused_size(root):
    """Total bytes currently sitting in the _unused folder."""
    unused = "{}/{}".format(_clean(root), UNUSED_FOLDER)
    total = 0
    count = 0
    for folder, _dirnames, filenames in os.walk(unused):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(folder, name))
                count += 1
            except OSError:
                pass
    return count, total


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

(COL_ON, COL_EXT, COL_FILE, COL_FOLDER, COL_REASON, COL_SIZE,
 COL_AGE) = range(7)

(SCOL_SCENE, SCOL_FOLDER, SCOL_USES, SCOL_INSIDE, SCOL_MISSING,
 SCOL_AGE) = range(6)

CHECK_COL_W = 28    # checkbox column, always this wide
MIN_COL_W = 90      # a wide column never shrinks below this

MISSING_COLOUR = "#ff6b6b"
DIM_COLOUR = "#9aa0a6"

# The banner above the table. Orange while the sibling scan has not run --
# that is the state where the list can quietly offer another shot's files --
# and neutral once it has.
WARN_STYLE = ("color:#ffb86b; background:#3a2f1c; padding:6px; "
              "border-radius:3px;")
INFO_STYLE = ("color:#9aa0a6; background:#242424; padding:6px; "
              "border-radius:3px;")


class SortableItem(QtWidgets.QTableWidgetItem):
    """
    A cell that sorts on a supplied key rather than its displayed text.

    Without this, Size would sort as a string -- "9.0 MB" landing between
    "8.3 KB" and "99.7 KB" -- and Modified would sort alphabetically, putting
    "2 months" before "3 days".
    """

    def __init__(self, text, key=None):
        super(SortableItem, self).__init__(text)
        self._key = text if key is None else key

    def __lt__(self, other):
        if isinstance(other, SortableItem):
            try:
                return self._key < other._key
            except TypeError:
                return str(self._key) < str(other._key)
        return super(SortableItem, self).__lt__(other)


class CleanerDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super(CleanerDialog, self).__init__(parent)
        self.setWindowTitle("Find Unused Assets  v{}".format(VERSION))
        self.resize(1120, 640)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)

        self.orphans = []           # every unused file, flat
        self.groups = []            # what the table shows: sequences collapsed
        self.group_sequences = True
        self.scenes = []
        self._scanned_scenes = False        # has the sibling scan been run
        self._scene_scan_cancelled = False
        self._did_initial_fit = False
        self._user_sized = False
        self._applying_fit = False
        self._build_ui()
        self.refresh()

    def showEvent(self, event):
        """
        Fit the columns the first time the dialog is actually shown. Doing it
        in __init__ measures a viewport that has not been laid out yet.
        """
        super(CleanerDialog, self).showEvent(event)
        if not self._did_initial_fit and self.orphans:
            self._did_initial_fit = True
            QtCore.QTimer.singleShot(0, self.fit_columns)

    def resizeEvent(self, event):
        """Re-budget columns on resize, unless the user sized them by hand."""
        super(CleanerDialog, self).resizeEvent(event)
        if self._did_initial_fit and self.orphans and not self._user_sized:
            QtCore.QTimer.singleShot(0, self.fit_columns)

    def _on_section_resized(self, _index, _old, _new):
        if not self._applying_fit:
            self._user_sized = True

    # -- construction -------------------------------------------------------

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        # Project root row
        root_row = QtWidgets.QHBoxLayout()
        root_row.addWidget(QtWidgets.QLabel("Project root:"))
        self.root_field = QtWidgets.QLineEdit(project_root())
        self.root_field.setToolTip(
            "Files under this folder are checked against the open scene.")
        root_row.addWidget(self.root_field, 1)
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(self._browse_root)
        root_row.addWidget(browse)
        rescan = QtWidgets.QPushButton("Rescan")
        rescan.clicked.connect(self.refresh)
        root_row.addWidget(rescan)
        layout.addLayout(root_row)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self._build_unused_tab(), "Unused files")
        self.tabs.addTab(self._build_scenes_tab(), "Other scenes")
        layout.addWidget(self.tabs, 1)

        # Status + actions
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QtWidgets.QHBoxLayout()
        self.restore_btn = QtWidgets.QPushButton("Restore _unused...")
        self.restore_btn.setToolTip(
            "Put everything in the _unused folder back where it came from.")
        self.restore_btn.clicked.connect(self._restore)
        buttons.addWidget(self.restore_btn)
        buttons.addStretch(1)

        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)

        self.run_btn = QtWidgets.QPushButton("Move to _unused")
        self.run_btn.setDefault(True)
        self.run_btn.clicked.connect(self._run)
        buttons.addWidget(self.run_btn)
        layout.addLayout(buttons)

    def _build_unused_tab(self):
        page = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)

        self.warning = QtWidgets.QLabel("")
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(WARN_STYLE)
        self.warning.hide()
        box.addWidget(self.warning)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["", "Type", "File", "Folder", "Why", "Size", "Modified"])
        self._prep_table(self.table)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        header = self.table.horizontalHeader()
        header.sectionResized.connect(self._on_section_resized)
        header.sectionDoubleClicked.connect(self._header_double_clicked)
        box.addWidget(self.table, 1)

        self.legend = QtWidgets.QLabel("")
        self.legend.setWordWrap(True)
        box.addWidget(self.legend)

        row = QtWidgets.QHBoxLayout()
        for label, slot in (("Select recommended", self._select_recommended),
                            ("All", self._select_all),
                            ("None", self._select_none),
                            ("Invert", self._select_invert)):
            btn = QtWidgets.QPushButton(label)
            btn.clicked.connect(slot)
            row.addWidget(btn)

        self.group_check = QtWidgets.QCheckBox("Group sequences")
        self.group_check.setChecked(True)
        self.group_check.setToolTip(
            "Collapse numbered frames into one row each. Turn off to see "
            "and tick individual frames.")
        self.group_check.toggled.connect(self._toggle_grouping)
        row.addWidget(self.group_check)

        row.addStretch(1)
        box.addLayout(row)
        return page

    def _build_scenes_tab(self):
        page = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(page)
        box.setContentsMargins(0, 8, 0, 0)

        blurb = QtWidgets.QLabel(
            "Other .hip files in this project, read straight off disk without "
            "opening them. This is not run automatically -- it reads every "
            "scene whole, which takes a moment on a big project. Once it has "
            "run, any file a sibling scene uses is marked <b>used by other "
            "scene</b> on the first tab and unticked.")
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color:#9aa0a6;")
        box.addWidget(blurb)

        # Scan row: the button, and a progress bar that only appears while
        # the scan is actually running.
        scan_row = QtWidgets.QHBoxLayout()
        self.scan_scenes_btn = QtWidgets.QPushButton("Scan other scenes")
        self.scan_scenes_btn.setToolTip(
            "Read every other .hip in the project and report what each one "
            "references.")
        self.scan_scenes_btn.clicked.connect(self._scan_scenes)
        scan_row.addWidget(self.scan_scenes_btn)

        self.scene_progress = QtWidgets.QProgressBar()
        self.scene_progress.setTextVisible(True)
        self.scene_progress.hide()
        scan_row.addWidget(self.scene_progress, 1)

        self.scene_cancel_btn = QtWidgets.QPushButton("Cancel")
        self.scene_cancel_btn.hide()
        self.scene_cancel_btn.clicked.connect(self._cancel_scene_scan)
        scan_row.addWidget(self.scene_cancel_btn)

        self.scene_status = QtWidgets.QLabel("Not scanned yet.")
        self.scene_status.setStyleSheet("color:#9aa0a6;")
        scan_row.addWidget(self.scene_status)
        scan_row.addStretch(1)
        box.addLayout(scan_row)

        splitter = QtWidgets.QSplitter(Qt.Vertical)

        self.scene_table = QtWidgets.QTableWidget(0, 6)
        self.scene_table.setHorizontalHeaderLabels(
            ["Scene", "Folder", "References", "In project", "Missing",
             "Modified"])
        self._prep_table(self.scene_table, checkable=False)
        self.scene_table.itemSelectionChanged.connect(self._on_scene_selected)
        self.scene_table.itemDoubleClicked.connect(self._on_scene_double_click)
        splitter.addWidget(self.scene_table)

        lower = QtWidgets.QWidget()
        lower_box = QtWidgets.QVBoxLayout(lower)
        lower_box.setContentsMargins(0, 6, 0, 0)
        self.scene_detail_label = QtWidgets.QLabel(
            "Select a scene to see what it references.")
        self.scene_detail_label.setStyleSheet("color:#9aa0a6;")
        lower_box.addWidget(self.scene_detail_label)

        self.scene_files = QtWidgets.QTableWidget(0, 3)
        self.scene_files.setHorizontalHeaderLabels(
            ["File", "Where", "On disk"])
        self._prep_table(self.scene_files, checkable=False)
        self.scene_files.customContextMenuRequested.connect(
            self._scene_files_menu)
        lower_box.addWidget(self.scene_files, 1)
        splitter.addWidget(lower)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        box.addWidget(splitter, 1)
        return page

    def _prep_table(self, table, checkable=True):
        """Shared table setup -- selection, sorting, context menu, look."""
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(True)
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        header = table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Interactive)
        if checkable:
            header.setSectionResizeMode(COL_ON, QtWidgets.QHeaderView.Fixed)
            table.setColumnWidth(COL_ON, CHECK_COL_W)

    # -- scanning -----------------------------------------------------------

    def _browse_root(self):
        start = self.root_field.text() or project_root()
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Project root", start)
        if chosen:
            self.root_field.setText(_clean(chosen))
            self.refresh()

    def refresh(self):
        root = _clean(self.root_field.text()) or project_root()
        if not root or not os.path.isdir(root):
            self.orphans, self.scenes = [], []
            self._regroup()
            self._populate()
            self.status.setText(
                "Project root does not exist. Browse to a folder to scan.")
            return

        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(Qt.WaitCursor))
        try:
            # Only the open scene. Reading the other .hip files is opt-in,
            # behind the button on the Other scenes tab.
            self.orphans, self.scenes = scan(root, check_other_scenes=False)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self._regroup()

        # A rescan invalidates whatever the last sibling scan concluded.
        self._scanned_scenes = False
        if hasattr(self, "scene_status"):
            self.scene_status.setText("Not scanned yet.")

        self._populate()
        self._populate_scenes()
        self._update_legend()
        self._update_status()
        if self.orphans and not self._user_sized:
            QtCore.QTimer.singleShot(0, self.fit_columns)

    # -- the unused table ---------------------------------------------------

    def _toggle_grouping(self, on):
        """Collapse or expand sequences without rescanning the disk."""
        self.group_sequences = bool(on)
        self._regroup()
        self._populate()
        self._update_status()
        if not self._user_sized:
            QtCore.QTimer.singleShot(0, self.fit_columns)

    def _regroup(self):
        """Rebuild the display rows from the flat orphan list."""
        self.groups = group_orphans(self.orphans, self.group_sequences)

    def _populate(self):
        table = self.table
        table.setSortingEnabled(False)
        table.blockSignals(True)
        table.setRowCount(0)

        for index, orphan in enumerate(self.groups):
            row = table.rowCount()
            table.insertRow(row)

            check = QtWidgets.QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                           Qt.ItemIsSelectable)
            # A sequence with only some frames ticked shows as partial rather
            # than lying in either direction.
            if orphan.partially_selected:
                check.setCheckState(Qt.PartiallyChecked)
            else:
                check.setCheckState(
                    Qt.Checked if orphan.selected else Qt.Unchecked)
            # Rows are keyed by their index in self.groups: a path is not
            # unique enough once a row stands for many files.
            check.setData(Qt.UserRole, index)
            table.setItem(row, COL_ON, check)

            ext = SortableItem(orphan.ext_label)
            ext.setForeground(QtGui.QColor(ext_colour(orphan.ext_label)))
            table.setItem(row, COL_EXT, ext)

            name = SortableItem(orphan.name)
            if orphan.is_sequence:
                shown = [o.name for o in orphan.orphans[:12]]
                tip = "{} files:".format(orphan.count)
                tip += "".join("\n  " + n for n in shown)
                if orphan.count > len(shown):
                    tip += "\n  ... and {} more".format(
                        orphan.count - len(shown))
                name.setToolTip(tip)
            else:
                name.setToolTip(orphan.path)
            table.setItem(row, COL_FILE, name)

            folder = SortableItem(orphan.folder)
            folder.setForeground(QtGui.QColor(DIM_COLOUR))
            table.setItem(row, COL_FOLDER, folder)

            reason = SortableItem(orphan.reason)
            reason.setForeground(
                QtGui.QColor(CONFIDENCE_COLOURS.get(orphan.reason,
                                                    DEFAULT_EXT_COLOUR)))
            tip = CONFIDENCE_HELP.get(orphan.reason, "")
            if orphan.other_scenes:
                names = "\n".join("  " + os.path.basename(s)
                                  for s in orphan.other_scenes[:8])
                tip += "\n\nUsed by:\n" + names
            reason.setToolTip(tip)
            table.setItem(row, COL_REASON, reason)

            size = SortableItem(_human(orphan.size_bytes), orphan.size_bytes)
            size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, COL_SIZE, size)

            # Sort newest-first by negating, so "3 days" beats "2 years".
            age = SortableItem(orphan.age, -orphan.mtime)
            age.setForeground(QtGui.QColor(DIM_COLOUR))
            table.setItem(row, COL_AGE, age)

        table.blockSignals(False)
        table.setSortingEnabled(True)

    def _ref_at(self, row):
        """The Group shown on this row, or None."""
        item = self.table.item(row, COL_ON)
        if item is None:
            return None
        index = item.data(Qt.UserRole)
        try:
            return self.groups[int(index)]
        except (TypeError, ValueError, IndexError):
            return None

    def _selected_rows(self):
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def _set_rows(self, rows, state):
        self.table.blockSignals(True)
        for row in rows:
            orphan = self._ref_at(row)
            if orphan is None:
                continue
            orphan.selected = state
            item = self.table.item(row, COL_ON)
            if item is not None:
                item.setCheckState(Qt.Checked if state else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_status()

    def _isolate_rows(self, rows):
        """Clear every tick, then select just these -- the menu default."""
        self._set_rows(range(self.table.rowCount()), False)
        self._set_rows(rows, True)

    def _rows_where(self, predicate):
        return [row for row in range(self.table.rowCount())
                if self._ref_at(row) is not None
                and predicate(self._ref_at(row))]

    def _on_item_changed(self, item):
        if item.column() != COL_ON:
            return
        orphan = self._ref_at(item.row())
        if orphan is None:
            return

        state = item.checkState()
        # A partly-ticked sequence resolves to fully ticked when clicked,
        # rather than leaving the user in a third state they cannot act on.
        selected = state != Qt.Unchecked
        orphan.selected = selected

        if state == Qt.PartiallyChecked:
            self.table.blockSignals(True)
            item.setCheckState(Qt.Checked)
            self.table.blockSignals(False)

        self._update_status()

    def _on_double_click(self, item):
        """
        Open the file itself. Looking at a mystery cache is the fastest way
        to decide whether it matters; Show in Explorer is on the menu for
        when the folder is what you wanted.
        """
        orphan = self._ref_at(item.row())
        if orphan is not None:
            self._open_file(orphan.path)

    def _reveal(self, path):
        """Show a file in Explorer. Windows only, quietly ignored elsewhere."""
        path = _clean(path)
        if not os.path.exists(path):
            path = os.path.dirname(path)
        try:
            if os.name == "nt":
                os.startfile(os.path.dirname(path))
            else:
                import subprocess
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass

    def _open_file(self, path):
        """
        Open a file in whatever the OS has associated with it.

        Worth having on a tool like this: the quickest way to decide whether
        a mystery cache or texture matters is to look at it.
        """
        path = _clean(path)
        if not os.path.isfile(path):
            hou.ui.displayMessage(
                "Not on disk any more:\n\n{}".format(path),
                severity=hou.severityType.Warning, title="Open file")
            return
        try:
            if os.name == "nt":
                os.startfile(path)
            else:
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, path])
        except Exception as exc:
            hou.ui.displayMessage(
                "Could not open:\n\n{}\n\n{}".format(path, exc),
                severity=hou.severityType.Warning, title="Open file")

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        orphan = self._ref_at(row)
        if orphan is None:
            return

        rows = self._selected_rows()
        # Right-clicking outside the selection acts on that row, the way a
        # file manager does.
        if row not in rows:
            rows = [row]
            self.table.clearSelection()
            self.table.selectRow(row)

        menu = QtWidgets.QMenu(self)

        # Count files, not rows -- one row can be a 240-frame sequence.
        picked = [self._ref_at(r) for r in rows]
        n_files = sum(g.count for g in picked if g is not None)

        if n_files > 1:
            menu.addAction(
                "Move these {} files now".format(n_files),
                lambda: self._move_refs(
                    picked, "Move {} files".format(n_files)))
        else:
            menu.addAction("Move this file now",
                           lambda: self._move_refs([orphan], "Move one file"))
        menu.addSeparator()

        menu.addAction("Select only these rows",
                       lambda: self._isolate_rows(rows))
        menu.addAction("Add to selection", lambda: self._set_rows(rows, True))
        menu.addAction("Deselect these rows",
                       lambda: self._set_rows(rows, False))
        menu.addSeparator()

        ext = orphan.ext_label
        menu.addAction(
            "Select only {} files".format(ext),
            lambda: self._isolate_rows(
                self._rows_where(lambda o: o.ext_label == ext)))
        folder = orphan.folder
        menu.addAction(
            "Select only this folder",
            lambda: self._isolate_rows(
                self._rows_where(lambda o: o.folder == folder)))
        reason = orphan.reason
        menu.addAction(
            "Select only '{}'".format(reason),
            lambda: self._isolate_rows(
                self._rows_where(lambda o: o.reason == reason)))
        menu.addSeparator()

        if orphan.other_scenes:
            menu.addAction("Show scenes using this file",
                           lambda: self._show_users(orphan))
        open_action = menu.addAction(
            "Open with default app",
            lambda: self._open_file(orphan.path))
        open_action.setEnabled(os.path.isfile(orphan.path))
        menu.addAction("Why is this here?", lambda: self._explain(orphan))
        menu.addAction("Copy path", lambda: QtWidgets.QApplication
                       .clipboard().setText(orphan.path))
        menu.addAction("Show in Explorer", lambda: self._reveal(orphan.path))
        menu.addAction("Fit columns", self.fit_columns)
        menu.exec_(self.table.viewport().mapToGlobal(pos))

    def _explain(self, group):
        """
        Say exactly why this row is listed, and what the scan matched on.

        If a file you know is referenced turns up here, this is what tells
        you whether the path simply did not match -- which is the report
        worth sending back.
        """
        orphan = group.orphans[0]
        used_paths, used_stems, _by = scene_references()

        lines = [
            "File on disk:",
            "    " + orphan.path,
            "",
            "Match key used by the scan:",
            "    " + _key(orphan.path),
            "",
            "Verdict: {}".format(group.reason),
            "",
            CONFIDENCE_HELP.get(group.reason, ""),
            "",
            "The open scene references {} path(s) and {} sequence "
            "stem(s).".format(len(used_paths), len(used_stems)),
        ]

        stem = frame_stem(orphan.path)
        if stem:
            lines += [
                "",
                "This file reads as frame {} of the sequence:".format(
                    frame_number(orphan.path)),
                "    " + stem,
                "    sequence known to the scene: {}".format(
                    "yes" if stem in used_stems else "no"),
            ]

        # The nearest referenced paths in the same folder, which is usually
        # enough to see a padding or spelling mismatch at a glance.
        folder = os.path.dirname(_key(orphan.path))
        nearby = sorted(p for p in used_paths if os.path.dirname(p) == folder)
        if nearby:
            lines += ["", "Referenced files in the same folder:"]
            lines += ["    " + os.path.basename(p) for p in nearby[:10]]
            if len(nearby) > 10:
                lines.append("    ... and {} more".format(len(nearby) - 10))
        else:
            lines += ["", "Nothing in this folder is referenced at all."]

        if group.other_scenes:
            lines += ["", "Referenced by these other scenes:"]
            lines += ["    " + os.path.basename(s)
                      for s in group.other_scenes[:10]]

        hou.ui.displayMessage("\n".join(lines), title="Why is this here?")

    def _show_users(self, orphan):
        """Jump to the other-scenes tab with this file's users listed."""
        self.tabs.setCurrentIndex(1)
        self.scene_detail_label.setText(
            "Scenes referencing <b>{}</b>".format(orphan.name))
        self._fill_ref_table(
            [(os.path.basename(s), s, "scene", os.path.exists(s))
             for s in orphan.other_scenes])

    # -- selection helpers --------------------------------------------------

    def _apply_states(self, chooser):
        """
        Re-tick every row from a function of the row.

        Setting Group.selected propagates to every frame underneath, so a
        sequence is always ticked or unticked as a whole here.
        """
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            orphan = self._ref_at(row)
            if orphan is None:
                continue
            orphan.selected = chooser(orphan)
            item = self.table.item(row, COL_ON)
            if item is not None:
                item.setCheckState(
                    Qt.Checked if orphan.selected else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_status()

    def _select_recommended(self):
        # Group.reason is the most cautious reason in the group, so a
        # sequence holding even one protected frame is not ticked.
        self._apply_states(lambda o: o.reason in AUTO_SELECT)

    def _select_all(self):
        self._apply_states(lambda o: True)

    def _select_none(self):
        self._apply_states(lambda o: False)

    def _select_invert(self):
        self._apply_states(lambda o: not o.selected)

    # -- the other-scenes tab ----------------------------------------------

    def _populate_scenes(self):
        table = self.scene_table
        table.setSortingEnabled(False)
        table.setRowCount(0)

        for scene in self.scenes:
            row = table.rowCount()
            table.insertRow(row)

            name = SortableItem(scene.name)
            name.setToolTip(scene.path)
            name.setData(Qt.UserRole, scene.path)
            table.setItem(row, SCOL_SCENE, name)

            folder = SortableItem(scene.folder)
            folder.setForeground(QtGui.QColor(DIM_COLOUR))
            table.setItem(row, SCOL_FOLDER, folder)

            total = len(scene.all_paths)
            uses = SortableItem(str(total), total)
            uses.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(row, SCOL_USES, uses)

            inside = len(scene.inside_paths)
            inside_item = SortableItem(str(inside), inside)
            inside_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            inside_item.setForeground(QtGui.QColor("#7ee787"))
            table.setItem(row, SCOL_INSIDE, inside_item)

            missing = len(scene.missing)
            missing_item = SortableItem(str(missing), missing)
            missing_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if missing:
                missing_item.setForeground(QtGui.QColor(MISSING_COLOUR))
            table.setItem(row, SCOL_MISSING, missing_item)

            age = SortableItem(_age(scene.mtime), -scene.mtime)
            age.setForeground(QtGui.QColor(DIM_COLOUR))
            table.setItem(row, SCOL_AGE, age)

        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

    def _cancel_scene_scan(self):
        self._scene_scan_cancelled = True

    def _scan_scenes(self):
        """
        Read every other .hip in the project, on demand.

        Runs on the main thread with processEvents so the progress bar moves
        and Cancel works. That is deliberate: a worker thread would need the
        results marshalled back and cannot be interrupted mid-read anyway,
        and the scan is IO-bound in chunks of one file.
        """
        root = _clean(self.root_field.text()) or project_root()
        if not root or not os.path.isdir(root):
            return

        try:
            current = hou.hipFile.path()
        except Exception:
            current = ""

        self._scene_scan_cancelled = False
        self.scan_scenes_btn.setEnabled(False)
        self.scene_progress.setValue(0)
        self.scene_progress.show()
        self.scene_cancel_btn.show()
        self.scene_status.setText("Scanning...")

        def progress(index, total, hip):
            self.scene_progress.setMaximum(max(1, total))
            self.scene_progress.setValue(index)
            self.scene_progress.setFormat(
                "%v / %m  {}".format(os.path.basename(hip)))
            QtWidgets.QApplication.processEvents()
            return not self._scene_scan_cancelled

        try:
            self.scenes, used_by = scan_other_scenes(root, current, progress)
        finally:
            self.scene_progress.hide()
            self.scene_cancel_btn.hide()
            self.scan_scenes_btn.setEnabled(True)

        # Re-tick from scratch, then apply what the scan found. Without the
        # reset, cancelling and rescanning would keep stale downgrades from
        # the previous run.
        self._select_recommended()
        shared = apply_other_scenes(self.orphans, used_by)

        self._scanned_scenes = not self._scene_scan_cancelled
        self._populate_scenes()
        self._populate()
        self._update_legend()
        self._update_status()

        if self._scene_scan_cancelled:
            self.scene_status.setText(
                "Cancelled after {} scene(s).".format(len(self.scenes)))
        else:
            self.scene_status.setText(
                "{} scene(s) read, {} file(s) protected.".format(
                    len(self.scenes), shared))

    def _scene_at(self, row):
        item = self.scene_table.item(row, SCOL_SCENE)
        if item is None:
            return None
        path = item.data(Qt.UserRole)
        for scene in self.scenes:
            if scene.path == path:
                return scene
        return None

    def _on_scene_selected(self):
        rows = sorted({i.row() for i in self.scene_table.selectedIndexes()})
        if not rows:
            return
        scene = self._scene_at(rows[0])
        if scene is None:
            return

        root = _clean(self.root_field.text())
        self.scene_detail_label.setText(
            "<b>{}</b> references {} file(s) -- {} inside the project, "
            "{} not on disk.".format(
                scene.name, len(scene.all_paths), len(scene.inside_paths),
                len(scene.missing)))

        rows_out = []
        for path in sorted(scene.all_paths):
            where = "in project" if is_inside(path, root) else "outside"
            rows_out.append((os.path.basename(path), path, where,
                             os.path.exists(path)))
        self._fill_ref_table(rows_out)

    def _fill_ref_table(self, rows):
        """Fill the lower table with (name, full path, where, exists) rows."""
        table = self.scene_files
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for name, path, where, exists in rows:
            row = table.rowCount()
            table.insertRow(row)

            item = SortableItem(name)
            item.setToolTip(path)
            item.setData(Qt.UserRole, path)
            table.setItem(row, 0, item)

            where_item = SortableItem(where)
            where_item.setForeground(QtGui.QColor(
                "#7ee787" if where == "in project" else DIM_COLOUR))
            table.setItem(row, 1, where_item)

            state = SortableItem("yes" if exists else "MISSING")
            if not exists:
                state.setForeground(QtGui.QColor(MISSING_COLOUR))
            table.setItem(row, 2, state)
        table.setSortingEnabled(True)
        table.resizeColumnsToContents()

    def _on_scene_double_click(self, item):
        scene = self._scene_at(item.row())
        if scene is not None:
            self._reveal(scene.path)

    def _scene_files_menu(self, pos):
        row = self.scene_files.rowAt(pos.y())
        if row < 0:
            return
        item = self.scene_files.item(row, 0)
        if item is None:
            return
        path = item.data(Qt.UserRole)
        menu = QtWidgets.QMenu(self)
        open_action = menu.addAction(
            "Open with default app", lambda: self._open_file(path))
        open_action.setEnabled(os.path.isfile(path))
        menu.addAction("Copy path", lambda: QtWidgets.QApplication
                       .clipboard().setText(path))
        menu.addAction("Show in Explorer", lambda: self._reveal(path))
        menu.exec_(self.scene_files.viewport().mapToGlobal(pos))

    # -- column fitting -----------------------------------------------------

    def fit_columns(self):
        """
        Budget the columns against the window width so long names and folders
        share what is left after the narrow columns have taken what they need.
        """
        table = self.table
        if table.rowCount() == 0:
            return
        self._applying_fit = True
        try:
            metrics = table.fontMetrics()
            available = table.viewport().width() - CHECK_COL_W - 8
            wide = [COL_FILE, COL_FOLDER]

            fixed = 0
            for col in (COL_EXT, COL_REASON, COL_SIZE, COL_AGE):
                header_item = table.horizontalHeaderItem(col)
                width = metrics.horizontalAdvance(
                    header_item.text() if header_item else "") + 24
                for row in range(table.rowCount()):
                    item = table.item(row, col)
                    if item is not None:
                        width = max(width, metrics.horizontalAdvance(
                            item.text()) + 24)
                table.setColumnWidth(col, width)
                fixed += width

            share = max(MIN_COL_W, int((available - fixed) / len(wide)))
            for col in wide:
                table.setColumnWidth(col, share)
            table.setColumnWidth(COL_ON, CHECK_COL_W)
        finally:
            self._applying_fit = False

    def _header_double_clicked(self, _index):
        self.fit_columns()

    # -- status -------------------------------------------------------------

    def _update_legend(self):
        seen = []
        for orphan in self.orphans:
            if orphan.reason not in seen:
                seen.append(orphan.reason)
        parts = []
        for reason in seen:
            colour = CONFIDENCE_COLOURS.get(reason, DEFAULT_EXT_COLOUR)
            parts.append('<span style="color:{}">&#9632;</span> {}'.format(
                colour, reason))
        self.legend.setText("&nbsp;&nbsp;".join(parts))

    def _update_status(self):
        chosen = [o for o in self.orphans if o.selected]
        total_bytes = sum(o.size_bytes for o in self.orphans)
        chosen_bytes = sum(o.size_bytes for o in chosen)

        root = _clean(self.root_field.text())
        kept, kept_bytes = unused_size(root)
        self.restore_btn.setEnabled(kept > 0)
        self.restore_btn.setText(
            "Restore _unused ({} files, {})".format(kept, _human(kept_bytes))
            if kept else "Restore _unused...")

        self.run_btn.setEnabled(bool(chosen))
        self.run_btn.setText(
            "Move {} file{} to _unused".format(
                len(chosen), "" if len(chosen) == 1 else "s")
            if chosen else "Move to _unused")

        collapsed = ""
        sequences = sum(1 for g in self.groups if g.is_sequence)
        if sequences:
            collapsed = " in {} rows ({} sequence{})".format(
                len(self.groups), sequences, "" if sequences == 1 else "s")

        self.status.setText(
            "{} unused file(s){}, {} on disk.   {} ticked, {} would be "
            "freed.".format(len(self.orphans), collapsed, _human(total_bytes),
                            len(chosen), _human(chosen_bytes)))

        # The honest caveat. Until the sibling scan has run, this list only
        # knows about the open scene -- which is exactly when it is most
        # likely to offer up another shot's textures.
        shared = len([o for o in self.orphans if o.other_scenes])
        self.warning.setStyleSheet(
            WARN_STYLE if not self._scanned_scenes else INFO_STYLE)
        if not self._scanned_scenes:
            self.warning.setText(
                "This is the <b>open scene only</b>. Other .hip files in the "
                "project have not been read, so a file another scene uses "
                "will look unused here. Run <b>Scan other scenes</b> on the "
                "second tab before moving anything in bulk.")
            self.warning.show()
        elif shared:
            self.warning.setText(
                "{} scene(s) read. {} file(s) below are referenced by another "
                ".hip and have been unticked.".format(
                    len(self.scenes), shared))
            self.warning.show()
        else:
            self.warning.setText(
                "{} other scene(s) read -- none of them reference anything "
                "in this list.".format(len(self.scenes)))
            self.warning.show()

    # -- actions ------------------------------------------------------------

    def _run(self):
        chosen = [o for o in self.orphans if o.selected]
        if not chosen:
            return
        self._move_refs(chosen, "Move {} file{}".format(
            len(chosen), "" if len(chosen) == 1 else "s"))

    def _move_refs(self, refs, title):
        """
        Move a set of rows. Rows may be Groups, so flatten to the actual
        files first -- move_out() works on Orphans, and a sequence row
        stands for every frame in it.
        """
        flat = []
        seen = set()
        for ref in refs:
            if ref is None:
                continue
            for orphan in getattr(ref, "orphans", [ref]):
                if orphan.path not in seen:
                    seen.add(orphan.path)
                    flat.append(orphan)
        refs = flat
        if not refs:
            return

        total_bytes = sum(r.size_bytes for r in refs)
        shared = [r for r in refs if r.other_scenes]

        message = ("Move {} file(s), {}, into:\n\n{}/{}\n\n"
                   "Nothing is deleted -- the files keep their folder "
                   "structure and can be put back with Restore.".format(
                       len(refs), _human(total_bytes),
                       _clean(self.root_field.text()), UNUSED_FOLDER))
        if shared:
            message += ("\n\nWARNING: {} of these are referenced by another "
                        ".hip in this project.".format(len(shared)))

        choice = hou.ui.displayMessage(
            message, buttons=("Move", "Cancel"),
            severity=(hou.severityType.Warning if shared
                      else hou.severityType.Message),
            close_choice=1, title=title)
        if choice != 0:
            return

        progress_dialog = QtWidgets.QProgressDialog(
            "Moving files...", "Cancel", 0, len(refs), self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setMinimumDuration(300)

        def progress(index, total, orphan):
            progress_dialog.setMaximum(total)
            progress_dialog.setValue(index)
            progress_dialog.setLabelText(orphan.name)
            QtWidgets.QApplication.processEvents()
            return not progress_dialog.wasCanceled()

        moved, freed, errors = move_out(refs, progress)
        progress_dialog.close()

        self.refresh()

        summary = "Moved {} file(s), {} freed in the project folder.".format(
            moved, _human(freed))
        if errors:
            summary += "\n\n{} problem(s):\n".format(len(errors))
            summary += "\n".join(errors[:12])
            if len(errors) > 12:
                summary += "\n... and {} more.".format(len(errors) - 12)

        hou.ui.displayMessage(
            summary,
            severity=(hou.severityType.Warning if errors
                      else hou.severityType.Message),
            title="Asset Cleaner")

    def _restore(self):
        root = _clean(self.root_field.text())
        kept, kept_bytes = unused_size(root)
        if not kept:
            return

        choice = hou.ui.displayMessage(
            "Put all {} file(s) ({}) in {}/{} back where they came "
            "from?".format(kept, _human(kept_bytes), root, UNUSED_FOLDER),
            buttons=("Restore", "Cancel"), close_choice=1,
            title="Restore unused files")
        if choice != 0:
            return

        restored, errors = restore(root)
        self.refresh()

        summary = "Restored {} file(s).".format(restored)
        if errors:
            summary += "\n\n{} problem(s):\n".format(len(errors))
            summary += "\n".join(errors[:12])

        hou.ui.displayMessage(
            summary,
            severity=(hou.severityType.Warning if errors
                      else hou.severityType.Message),
            title="Asset Cleaner")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_dialog = None


def main(kwargs=None):
    global _dialog

    if hou.hipFile.path().endswith("untitled.hip") and not hou.getenv("JOB"):
        hou.ui.displayMessage(
            "Save the scene first so the project root can be determined.",
            severity=hou.severityType.Warning)
        return

    if _dialog is not None:
        try:
            _dialog.close()
            _dialog.deleteLater()
        except Exception:
            pass

    _dialog = CleanerDialog(parent=hou.qt.mainWindow())
    _dialog.show()
    return _dialog
