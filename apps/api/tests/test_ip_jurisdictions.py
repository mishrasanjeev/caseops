"""The web jurisdiction mirror agrees with the API vocabulary (BUG-014)."""

from __future__ import annotations

import re
from pathlib import Path

from caseops_api.core.jurisdictions import (
    ISO_3166_ALPHA_2,
    JURISDICTION_ALIASES,
    REGIONAL_CODES,
    canonical_jurisdiction,
)

WEB_MIRROR = Path(__file__).resolve().parents[2] / "web" / "lib" / "ip" / "jurisdictions.ts"


def test_vocabulary_is_iso_alpha_2_plus_regional_codes() -> None:
    assert len(ISO_3166_ALPHA_2) == 249
    assert REGIONAL_CODES == {"EM", "WO", "EP"}
    assert canonical_jurisdiction(" india ") == "IN"
    assert canonical_jurisdiction("United  Kingdom") == "GB"
    assert canonical_jurisdiction("in") == "IN"
    assert canonical_jurisdiction("Narnia") is None
    assert canonical_jurisdiction("") is None
    assert set(JURISDICTION_ALIASES.values()) <= ISO_3166_ALPHA_2 | REGIONAL_CODES


def test_web_mirror_matches_the_api_vocabulary() -> None:
    source = WEB_MIRROR.read_text(encoding="utf-8")
    block = source.split("export const ISO_3166_ALPHA_2 = (", 1)[1].split(").split", 1)[0]
    web_codes = set(" ".join(re.findall(r'"([A-Z ]+)"', block)).split())
    assert web_codes == ISO_3166_ALPHA_2
    regional = source.split("export const REGIONAL_CODES = [", 1)[1].split("]", 1)[0]
    assert set(re.findall(r'"([A-Z]{2})"', regional)) == REGIONAL_CODES
    aliases = source.split("export const JURISDICTION_ALIASES", 1)[1].split("};", 1)[0]
    web_aliases = {
        (quoted or bare): code
        for quoted, bare, code in re.findall(
            r'^\s*(?:"([A-Z ]+)"|([A-Z]+)): "([A-Z]{2})",$', aliases, flags=re.MULTILINE
        )
    }
    assert web_aliases == JURISDICTION_ALIASES
