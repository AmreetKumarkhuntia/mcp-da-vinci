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
