"""Framework-free core for Scribe.

Hard rule: nothing in this package may import PySide6, resolve.*, or
fusionscript. The Qt panel, the CLI, and any later front-end sit on top of this;
the dependency never runs the other way. Allowed imports are stdlib plus
faster_whisper / ctranslate2 / numpy / soundfile / imageio_ffmpeg / av.

The fusionscript half of that rule is not paranoia. Scribe's panel is an
external process, and on the free edition of Resolve scriptapp() returns None to
an external process — so "just try the API" cannot work here, and code that
tries it fails in a way that looks like a bug rather than a licence. Talking to
Resolve is the job of the launcher script that runs *inside* Resolve; see
resolve_script/.

A test enforces this. It is the same rule Stash uses (stashlib/__init__.py), for
the same reason: it is what lets the core be exercised from a plain WSL python
on a machine with no Resolve and no Qt.
"""
