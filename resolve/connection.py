"""Connection layer to a running DaVinci Resolve instance.

Resolve scripting works by importing ``DaVinciResolveScript``, which loads the
native ``fusionscript.dll`` and talks to the running Resolve process over local
IPC. That DLL is a Windows binary, so this module (and the whole server) must be
run by **Windows Python** — a Linux/WSL interpreter cannot load it.

The import + discovery logic mirrors the official
``.../Scripting/Examples/python_get_resolve.py`` shipped with Resolve, with
env-var fallbacks baked in so the server connects regardless of how it was
launched (Claude Code, MCP Inspector, or a bare ``python.exe`` invocation).
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sys

# --- Machine-specific defaults -------------------------------------------------
# These match this install (Resolve on D:, scripting docs on C:). They are only
# applied when the corresponding environment variable is not already set, so an
# explicit launcher config always wins.
_DEFAULT_SCRIPT_API = (
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting"
)
_DEFAULT_SCRIPT_LIB = r"D:\Program Files\BlackMagic\fusionscript.dll"

_resolve = None  # cached Resolve handle


def _apply_env_fallbacks() -> None:
    """Populate the env vars / sys.path Resolve's module expects, if missing."""
    os.environ.setdefault("RESOLVE_SCRIPT_API", _DEFAULT_SCRIPT_API)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", _DEFAULT_SCRIPT_LIB)

    modules_dir = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    if modules_dir not in sys.path:
        sys.path.append(modules_dir)


def _import_dvr_script():
    """Import the DaVinciResolveScript module, falling back to its absolute path."""
    try:
        import DaVinciResolveScript as dvr  # type: ignore

        return dvr
    except ImportError:
        module_path = os.path.join(
            os.environ["RESOLVE_SCRIPT_API"], "Modules", "DaVinciResolveScript.py"
        )
        spec = importlib.util.spec_from_file_location(
            "DaVinciResolveScript", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(
                "Could not locate DaVinciResolveScript module at "
                f"{module_path}. Set RESOLVE_SCRIPT_API to the Scripting folder."
            )
        dvr = importlib.util.module_from_spec(spec)
        sys.modules["DaVinciResolveScript"] = dvr
        spec.loader.exec_module(dvr)
        return dvr


def get_resolve(refresh: bool = False):
    """Return a connected Resolve handle (cached).

    Raises a descriptive error when Resolve can't be reached so the message
    surfaces to the model instead of an opaque ``None``.
    """
    global _resolve
    if _resolve is not None and not refresh:
        return _resolve

    _apply_env_fallbacks()
    dvr = _import_dvr_script()
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError(
            "Could not connect to DaVinci Resolve. Checklist: "
            "(1) Resolve is running; "
            "(2) Preferences > System > General > 'External scripting using' is set to 'Local'; "
            "(3) external scripting requires DaVinci Resolve Studio (not the free edition); "
            "(4) this server is run by Windows Python so it can load fusionscript.dll."
        )
    _resolve = resolve
    return _resolve


# --- Convenience accessors -----------------------------------------------------
def get_project_manager():
    return get_resolve().GetProjectManager()


def get_current_project():
    project = get_project_manager().GetCurrentProject()
    if project is None:
        raise RuntimeError("No project is currently open in DaVinci Resolve.")
    return project


def get_media_pool():
    return get_current_project().GetMediaPool()


def get_current_timeline():
    timeline = get_current_project().GetCurrentTimeline()
    if timeline is None:
        raise RuntimeError(
            "No timeline is currently active. Open or create a timeline first."
        )
    return timeline


def find_timeline_by_name(name: str):
    """Return the timeline with the given name, or raise if not found."""
    project = get_current_project()
    for idx in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(idx)
        if timeline and timeline.GetName() == name:
            return timeline
    raise RuntimeError(f"No timeline named {name!r} found in the current project.")


def find_clips_by_name(names: list[str]):
    """Resolve a list of media-pool clip names to MediaPoolItem objects.

    Searches the root folder and all nested subfolders. Raises if any name is
    unmatched so the caller gets a clear error rather than a silent no-op.
    """
    wanted = list(names)
    found: dict[str, object] = {}

    def walk(folder):
        for clip in folder.GetClipList() or []:
            clip_name = clip.GetName()
            if clip_name in wanted and clip_name not in found:
                found[clip_name] = clip
        for sub in folder.GetSubFolderList() or []:
            walk(sub)

    walk(get_media_pool().GetRootFolder())

    missing = [n for n in wanted if n not in found]
    if missing:
        raise RuntimeError(f"Clips not found in media pool: {missing}")
    return [found[n] for n in wanted]


def frame_to_timecode(frame: int, fps: float) -> str:
    """Absolute timeline frame -> "HH:MM:SS:FF" at the nominal integer rate.

    Non-drop math (23.976 -> 24, 29.97 -> 30); for drop-frame timelines pass a
    timecode string to the calling tool instead of a frame number.
    """
    nominal = round(fps)
    total_seconds, ff = divmod(int(frame), nominal)
    mm, ss = divmod(total_seconds, 60)
    hh, mm = divmod(mm, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


# --- Fusion accessors ----------------------------------------------------------
def get_fusion():
    """Return the Fusion application object."""
    return get_resolve().Fusion()


def get_bmd():
    """Return the native fusionscript module (bmd utilities: readfile/writefile).

    DaVinciResolveScript aliases itself to the loaded fusionscript DLL module,
    so after get_resolve() the module is already in sys.modules.
    """
    get_resolve()  # ensures fusionscript.dll is loaded
    for name in ("fusionscript", "DaVinciResolveScript", "BlackmagicFusion"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "readfile"):
            return mod
    raise RuntimeError(
        "Fusion's scripting module is unavailable (no loaded module exposes "
        "readfile). This should not happen once get_resolve() has connected."
    )


def get_current_video_item(clip_name: str | None = None):
    """Return a timeline video item — the playhead clip, or one matched by name.

    When ``clip_name`` is given, scans every video track of the current timeline
    for a clip whose name matches (mirrors :func:`find_clips_by_name`).
    """
    timeline = get_current_timeline()
    if clip_name is None:
        item = timeline.GetCurrentVideoItem()
        if item is None:
            raise RuntimeError(
                "No video clip under the playhead. Move the playhead onto a clip "
                "or pass clip_name."
            )
        return item

    for idx in range(1, timeline.GetTrackCount("video") + 1):
        for item in timeline.GetItemListInTrack("video", idx) or []:
            if item.GetName() == clip_name:
                return item
    raise RuntimeError(f"No video clip named {clip_name!r} in the current timeline.")


def get_comp(
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
    create: bool = False,
):
    """Resolve the target Fusion composition.

    Picks the clip (playhead or ``clip_name``), then the comp by ``comp_name`` or
    1-based ``comp_index``. With ``create=True`` an empty comp is added when the
    clip has none. Falls back to the Fusion page's current comp if there is no
    current video item.
    """
    try:
        item = get_current_video_item(clip_name)
    except RuntimeError:
        if clip_name is None:
            comp = get_fusion().GetCurrentComp()
            if comp is not None:
                return comp
        raise

    count = item.GetFusionCompCount()
    if count < 1:
        if create:
            comp = item.AddFusionComp()
            if comp is None:
                raise RuntimeError("Failed to add a Fusion composition to the clip.")
            return comp
        raise RuntimeError(
            f"Clip {item.GetName()!r} has no Fusion composition. "
            "Call fusion_add_comp first (or pass create=True)."
        )

    if comp_name:
        comp = item.GetFusionCompByName(comp_name)
        if comp is None:
            raise RuntimeError(
                f"No Fusion comp named {comp_name!r} on clip {item.GetName()!r}. "
                f"Available: {item.GetFusionCompNameList()}"
            )
        return _require_live_comp(comp, item)

    if not 1 <= comp_index <= count:
        raise RuntimeError(
            f"comp_index {comp_index} out of range (clip has {count} comp(s))."
        )
    return _require_live_comp(item.GetFusionCompByIndex(comp_index), item)


def _require_live_comp(comp, item):
    """Guard against stale comp handles.

    Resolve only exposes a scriptable comp for the clip whose comp is loaded
    (normally the current video item); other clips' handles answer with an
    empty tool list. Every real timeline comp has at least MediaOut1, so an
    empty list means "not loaded", not "empty comp".
    """
    if comp is not None and (comp.GetToolList() or {}):
        return comp
    raise RuntimeError(
        f"The Fusion comp on clip {item.GetName()!r} is not currently loaded, "
        "so it cannot be scripted. Move the playhead onto that clip — it must "
        "be the topmost visible clip (set_playhead, or disable covering "
        "tracks) — then retry."
    )


def find_fusion_tool(comp, name: str):
    """Return the named tool in a comp, or raise listing the available names."""
    tool = comp.FindTool(name)
    if tool is None:
        available = [
            t.GetAttrs().get("TOOLS_Name") for t in (comp.GetToolList() or {}).values()
        ]
        raise RuntimeError(f"No node named {name!r} in comp. Available: {available}")
    return tool


@contextlib.contextmanager
def comp_lock(comp):
    """Wrap a batch of comp edits in Lock()/Unlock() for speed and UI stability."""
    comp.Lock()
    try:
        yield comp
    finally:
        comp.Unlock()


def to_jsonable(obj):
    """Coerce Fusion setting/keyframe tables into JSON-safe Python values."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    # Fusion PyRemoteObject and other opaque handles -> string repr.
    return str(obj)
