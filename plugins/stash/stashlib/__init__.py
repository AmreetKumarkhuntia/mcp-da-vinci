"""Framework-free core for the meme/SFX library.

Hard rule: nothing in this package may import PySide6 or resolve.* . The Qt
panel, and any later front-end, sit on top of this; the dependency never runs
the other way. Allowed imports are stdlib plus soundfile / numpy / Pillow /
imageio_ffmpeg.
"""
