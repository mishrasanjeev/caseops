"""Canonical IP jurisdiction vocabulary: ISO-3166 alpha-2 plus EM, WO and EP.

Free text such as "India" or "uk" is normalised to the code a journal entry
carries, so a watch profile cannot be saved with a value that never matches.
The web mirror is apps/web/lib/ip/jurisdictions.ts (parity: tests/test_ip_jurisdictions.py).
"""

from __future__ import annotations

ISO_3166_ALPHA_2 = frozenset(
    (
        "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM "
        "BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX "
        "CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG "
        "GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR "
        "IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV "
        "LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE "
        "NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO "
        "RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF "
        "TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF "
        "WS YE YT ZA ZM ZW"
    ).split()
)
# EU trade marks (EUIPO), WIPO international registrations, European patents.
REGIONAL_CODES = frozenset({"EM", "WO", "EP"})
JURISDICTION_CODES = ISO_3166_ALPHA_2 | REGIONAL_CODES

# Names lawyers commonly type, keyed by upper-cased, space-collapsed text.
JURISDICTION_ALIASES: dict[str, str] = {
    "INDIA": "IN",
    "UK": "GB",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "USA": "US",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "CHINA": "CN",
    "JAPAN": "JP",
    "SINGAPORE": "SG",
    "AUSTRALIA": "AU",
    "CANADA": "CA",
    "GERMANY": "DE",
    "FRANCE": "FR",
    "UAE": "AE",
    "UNITED ARAB EMIRATES": "AE",
    "EU": "EM",
    "EUIPO": "EM",
    "EUROPEAN UNION": "EM",
    "WIPO": "WO",
    "MADRID": "WO",
    "INTERNATIONAL": "WO",
    "EPO": "EP",
    "EUROPEAN PATENT OFFICE": "EP",
}

JURISDICTION_HINT = (
    "Use a two-letter country code (for example IN for India), EM for EU trade marks, "
    "WO for international registrations or EP for European patents."
)


def canonical_jurisdiction(value: str) -> str | None:
    """The canonical code for a typed jurisdiction, or None when unknown."""

    key = " ".join(value.strip().upper().split())
    code = JURISDICTION_ALIASES.get(key, key)
    return code if code in JURISDICTION_CODES else None
