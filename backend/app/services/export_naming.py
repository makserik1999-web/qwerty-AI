"""Turning a question into a filename someone can find on their disk.

"video_a3f19c.mp4" in a downloads folder is indistinguishable from every other
one. The question the video answers is the only name that means anything, so
that is what gets used - transliterated, because a Kazakh filename is a real
problem on the way to a school computer running Windows in a legacy codepage.

Two names are produced for every download, which is what RFC 6266 is for: an
ASCII `filename` every client understands, and a `filename*` in UTF-8 for the
ones that do. Modern browsers take the second and show the original wording;
older ones fall back to the transliteration rather than to mojibake.
"""

import re
import unicodedata
from urllib.parse import quote

# Kazakh-specific letters first: they are not in the Russian table, and
# falling through to NFKD would drop them entirely rather than transliterate.
_TRANSLITERATION = {
    "ә": "a", "ғ": "g", "қ": "q", "ң": "n", "ө": "o",
    "ұ": "u", "ү": "u", "һ": "h", "і": "i",
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Everything a filesystem or a header would object to. Control characters are
# in here too: a newline in a filename is header injection, not a typo.
_UNSAFE = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]+')
_SEPARATORS = re.compile(r"[\s_]+")
_REPEATED_DASH = re.compile(r"-{2,}")

MAX_STEM = 60
FALLBACK_STEM = "anyq-export"


def transliterate(text: str) -> str:
    """Cyrillic (Kazakh included) to ASCII, leaving Latin text alone."""
    out = []
    for char in text:
        lower = char.lower()
        if lower in _TRANSLITERATION:
            replacement = _TRANSLITERATION[lower]
            # capitalize(), not upper(): "ж" maps to "zh", and an
            # upper-cased "Ж" is "Zh" - "ZH" reads as an acronym.
            out.append(replacement.capitalize() if char.isupper() else replacement)
        else:
            out.append(char)
    return "".join(out)


def _clean_stem(text: str) -> str:
    cleaned = _UNSAFE.sub(" ", (text or "").strip())
    cleaned = _SEPARATORS.sub("-", cleaned)
    cleaned = _REPEATED_DASH.sub("-", cleaned).strip("-. ")
    return cleaned[:MAX_STEM].strip("-. ")


def download_filename(title: str, suffix: str) -> str:
    """A readable name for the download, in the original script.

    Returns the name only - never a path. The caller decides where it goes,
    and nothing here can produce a separator that would make it a path.
    """
    stem = _clean_stem(title) or FALLBACK_STEM
    return f"{stem}{suffix}"


def ascii_filename(name: str) -> str:
    """The `filename` half: transliterated, then stripped to plain ASCII."""
    transliterated = transliterate(name)
    # Anything still non-ASCII (accents, stray scripts) is decomposed and its
    # marks dropped, so "é" becomes "e" rather than disappearing.
    decomposed = unicodedata.normalize("NFKD", transliterated)
    stripped = decomposed.encode("ascii", "ignore").decode("ascii")
    stem, _, suffix = stripped.rpartition(".")
    if not stem:
        return f"{FALLBACK_STEM}.{suffix}" if suffix else FALLBACK_STEM
    cleaned = _clean_stem(stem) or FALLBACK_STEM
    return f"{cleaned}.{suffix}" if suffix else cleaned


def content_disposition(name: str, disposition: str = "attachment") -> str:
    """An RFC 6266 header carrying both spellings of the name."""
    ascii_name = ascii_filename(name)
    # quote() with an empty safe set percent-encodes everything a header
    # parser could misread, which is what filename* expects.
    encoded = quote(name, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
