"""Turn a raw filename stem into searchable text.

The library mixes several naming regimes that defeat naive substring matching:

    WaterPourChalice_S011WR.87.mp3          glued CamelCase + vendor serial
    MMFX_CHIME BRIGHT PERCUSSIVE_SB01.174   vendor prefix + SCREAMING CASE
    MarimbaAscend_BWU.148.mp3               vendor serial with no digits
    Ah Shit Here We Go Again - GTA Sound Effect (HD) ( 160kbps ).mp3
    yt1s.com - Best Rage Of The Day  Episode 11_1080p.mp4
    AYAYAYAYYYY - AWAKEN - Green Screen [Mpgun.com].mp4

Typing "water pour" must find the first; typing "sound effect" must not match
600 files equally. So every stem is reduced to lowercase content words, with
vendor codes, ripper-site tags, resolution/codec markers and boilerplate
stripped.

Run `python.exe -m stashlib.normalize` to check the built-in corpus.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------- patterns ---

# Sound-library serial suffix: _S011WR.87, _AP1.758, _SB01.174, _BWU.148.
# The digit run before the dot is optional — _BWU.148 has none.
_VENDOR_SUFFIX = re.compile(r"_[A-Z]{1,4}\d*[A-Z]*\.\d+$")

# Vendor prefix on otherwise-readable names: MMFX_CHIME MELODY -> CHIME MELODY.
_VENDOR_PREFIX = re.compile(r"^(?:MMFX|SFX|SND|FX)_", re.I)

# Ripper-site litter: a leading "yt1s.com - ", or a bare "[Mpgun.com]" tag.
_DOMAIN = re.compile(r"\b[\w-]+\.(?:com|net|org|io|to|cc|me)\b", re.I)

# Boilerplate that appears on hundreds of files and so carries no signal.
_NOISE = re.compile(
    r"\b\d+\s*kbps\b"
    r"|\b(?:full\s+)?hd\b"
    r"|\b\d{3,4}p\b"  # 720p, 1080p
    r"|\bh\s*\.?\s*264\b|\bx\s*264\b|\bmp4\b"
    r"|\bsound\s+effects?\b|\bsounds?\s+fx\b"
    r"|\bfree\s+download\b|\bcopyright\s+free\b"
    r"|\boriginal\s+meme\b"
    r"|\bsrmp3\b",
    re.I,
)

# Split glued CamelCase. Deliberately no (?<=[0-9]) lookbehind: that would
# shatter 3D / 4K / H264 into meaningless fragments.
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_PUNCT = re.compile(r"""[_\-.+()\[\]{}!?,;:'"~@#$%^&*/\\|<>]+""")
_SPACE = re.compile(r"\s+")

# Pure-digit tokens of 3+ digits are serials (2633573605, 160). One and two
# digit tokens are kept — "3 2 1 GO COUNTDOWN" is a real, searchable name.
_SERIAL_TOKEN = re.compile(r"^\d{3,}$")


def normalize(stem: str) -> str:
    """Reduce a filename stem (no extension) to lowercase searchable words."""
    text = _VENDOR_SUFFIX.sub("", stem)
    text = _DOMAIN.sub(" ", text)
    text = _VENDOR_PREFIX.sub("", text)
    text = _CAMEL.sub(" ", text)
    # Punctuation is flattened before noise removal: "_" is a regex word
    # character, so "Episode 11_1080p" hides 1080p behind a non-boundary.
    text = _PUNCT.sub(" ", text)
    text = _NOISE.sub(" ", text)
    text = _SPACE.sub(" ", text).strip().lower()

    out: list[str] = []
    for token in text.split():
        if _SERIAL_TOKEN.match(token):
            continue
        # "squeaky door openingsqueaky door opening" -> collapse the repeat
        if out and out[-1] == token:
            continue
        out.append(token)
    return " ".join(out)


def tokenize(text: str) -> list[str]:
    """Split an already-normalized string, or a user query, into match tokens."""
    return normalize(text).split()


# ---------------------------------------------------------------- selftest ---

# Real stems from D:\videos. Expected values are what search must be able to
# hit; update deliberately, and re-run after any pattern change.
CORPUS: list[tuple[str, str]] = [
    ("WaterPourChalice_S011WR.87", "water pour chalice"),
    ("MMFX_CHIME BRIGHT PERCUSSIVE_SB01.174", "chime bright percussive"),
    ("MarimbaAscend_BWU.148", "marimba ascend"),
    ("MultimediaPositive_S011TE.713", "multimedia positive"),
    ("GunShotgun_S08WA.519", "gun shotgun"),
    ("HammerNailHit_S08IN.583", "hammer nail hit"),
    ("TirePuncture_SEU01.48", "tire puncture"),
    ("brick_01", "brick 01"),
    ("AirHorn 1", "air horn 1"),
    ("Air Horn sound effect", "air horn"),
    ("3D Thug Life Green Screen [Full HD]", "3d thug life green screen"),
    ("3 2 1 GO COUNTDOWN", "3 2 1 go countdown"),
    (
        "Ah Shit Here We Go Again - GTA Sound Effect (HD) ( 160kbps )",
        "ah shit here we go again gta",
    ),
    ("I choose you! (Pokemon Anime) - Sound Effect ", "i choose you pokemon anime"),
    ("yt1s.com - Best Rage Of The Day  Episode 11_1080p", "best rage of the day episode 11"),
    ("AYAYAYAYYYY - AWAKEN - Green Screen - Pantalla Verde [Mpgun.com]",
     "ayayayayyyy awaken green screen pantalla verde"),
    ("Duck Meme Hd Template - This is Assam (720p, h264)", "duck meme template this is assam"),
    ("Hell_s Kitchen Dramatic Sound (Waterphone) - Sound Effect (HD) ( 160kbps )",
     "hell s kitchen dramatic sound waterphone"),
    ("Eww dude WTF (Original meme HD)", "eww dude wtf"),
    ("subject-divine-representation-jesus-christ-260nw-2633573605",
     "subject divine representation jesus christ 260nw"),
]


def _selftest() -> int:
    failures = 0
    for stem, expected in CORPUS:
        actual = normalize(stem)
        ok = actual == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'}  {stem!r}\n      -> {actual!r}")
        if not ok:
            print(f"      expected {expected!r}")
    print(f"\n{len(CORPUS) - failures}/{len(CORPUS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
