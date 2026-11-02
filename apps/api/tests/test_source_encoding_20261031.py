"""No Windows-1252 mojibake in API source strings.

Ram 2026-10-30 (BUG-005/ENH-017): the web app shipped UTF-8 punctuation that
had been saved through a Windows-1252 round trip (a middle dot rendered as
capital A-circumflex plus the dot). The web guard lives in
apps/web/lib/source-encoding.test.ts; this is the same check for API strings
that reach users through problem details, exports and notifications. The
signatures are built from code points so this file never matches itself.
"""

from __future__ import annotations

import re
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"

_LATIN1_SYMBOLS = "".join(chr(code) for code in range(0xA0, 0xC0))
_CONTINUATIONS = "".join(chr(code) for code in range(0x80, 0xC0)) + "".join(
    chr(code)
    for code in (0x152, 0x153, 0x160, 0x161, 0x178, 0x17D, 0x17E, 0x192, 0x2C6, 0x2DC)
    + tuple(range(0x2013, 0x2015))
    + tuple(range(0x2018, 0x201F))
    + tuple(range(0x2020, 0x2023))
    + (0x2026, 0x2030, 0x2039, 0x203A, 0x20AC, 0x2122)
)
MOJIBAKE = {
    "A-circumflex + Latin-1 symbol": re.compile(chr(0xC2) + "[" + re.escape(_LATIN1_SYMBOLS) + "]"),
    "A-tilde + continuation": re.compile(chr(0xC3) + "[" + re.escape(_CONTINUATIONS) + "]"),
    "a-circumflex + euro sign": re.compile(chr(0xE2) + chr(0x20AC)),
    "byte-order mark as Windows-1252": re.compile(chr(0xEF) + chr(0xBB) + chr(0xBF)),
}


def _findings(text: str) -> list[str]:
    return [
        f"{number}: {name}"
        for number, line in enumerate(text.splitlines(), start=1)
        for name, pattern in MOJIBAKE.items()
        if pattern.search(line)
    ]


def test_signatures_match_the_garbled_text_and_not_the_intended_text() -> None:
    middle_dot_garbled = chr(0xC2) + chr(0xB7)
    em_dash_garbled = chr(0xE2) + chr(0x20AC) + chr(0x201D)
    e_acute_garbled = chr(0xC3) + chr(0xA9)
    assert _findings(f"candidate {middle_dot_garbled} triage")
    assert _findings(f"Provisional {em_dash_garbled} source")
    assert _findings(f"Caf{e_acute_garbled}")
    intended = "candidate · triage — Café ₹ हिंदी"
    assert _findings(intended) == []


def test_api_source_has_no_windows_1252_mojibake() -> None:
    files = sorted(SOURCE_ROOT.rglob("*.py"))
    assert len(files) > 100
    offenders = [
        f"{path.relative_to(SOURCE_ROOT).as_posix()}:{finding}"
        for path in files
        for finding in _findings(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
