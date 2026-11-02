"""Canonical filing-jurisdiction vocabulary for foreign-associate work.

Outside-counsel profiles store their jurisdictions as free text, and the same
field also holds domestic litigation values such as "Delhi High Court". A
foreign filing target, however, is a country or a regional office. Matching
free text against free text meant "UK", "GB" and "United Kingdom" never met
(Ram 2026-10-30, BUG-009). This module is the single vocabulary: ISO 3166-1
alpha-2 country codes plus the regional offices EM (EUIPO), WO (WIPO) and EP
(EPO). Stored text is never migrated; it is normalized when it is read and
matched, so the picker options and the create/reassign validators share one
predicate (filing_jurisdiction_matches).

Country names are the English CLDR region names.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

COUNTRY_NAMES: dict[str, str] = {
    "AD": "Andorra",
    "AE": "United Arab Emirates",
    "AF": "Afghanistan",
    "AG": "Antigua & Barbuda",
    "AI": "Anguilla",
    "AL": "Albania",
    "AM": "Armenia",
    "AO": "Angola",
    "AQ": "Antarctica",
    "AR": "Argentina",
    "AS": "American Samoa",
    "AT": "Austria",
    "AU": "Australia",
    "AW": "Aruba",
    "AX": "Åland Islands",
    "AZ": "Azerbaijan",
    "BA": "Bosnia & Herzegovina",
    "BB": "Barbados",
    "BD": "Bangladesh",
    "BE": "Belgium",
    "BF": "Burkina Faso",
    "BG": "Bulgaria",
    "BH": "Bahrain",
    "BI": "Burundi",
    "BJ": "Benin",
    "BL": "St. Barthélemy",
    "BM": "Bermuda",
    "BN": "Brunei",
    "BO": "Bolivia",
    "BQ": "Caribbean Netherlands",
    "BR": "Brazil",
    "BS": "Bahamas",
    "BT": "Bhutan",
    "BV": "Bouvet Island",
    "BW": "Botswana",
    "BY": "Belarus",
    "BZ": "Belize",
    "CA": "Canada",
    "CC": "Cocos (Keeling) Islands",
    "CD": "Congo - Kinshasa",
    "CF": "Central African Republic",
    "CG": "Congo - Brazzaville",
    "CH": "Switzerland",
    "CI": "Côte d'Ivoire",
    "CK": "Cook Islands",
    "CL": "Chile",
    "CM": "Cameroon",
    "CN": "China",
    "CO": "Colombia",
    "CR": "Costa Rica",
    "CU": "Cuba",
    "CV": "Cape Verde",
    "CW": "Curaçao",
    "CX": "Christmas Island",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DJ": "Djibouti",
    "DK": "Denmark",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "DZ": "Algeria",
    "EC": "Ecuador",
    "EE": "Estonia",
    "EG": "Egypt",
    "EH": "Western Sahara",
    "ER": "Eritrea",
    "ES": "Spain",
    "ET": "Ethiopia",
    "FI": "Finland",
    "FJ": "Fiji",
    "FK": "Falkland Islands",
    "FM": "Micronesia",
    "FO": "Faroe Islands",
    "FR": "France",
    "GA": "Gabon",
    "GB": "United Kingdom",
    "GD": "Grenada",
    "GE": "Georgia",
    "GF": "French Guiana",
    "GG": "Guernsey",
    "GH": "Ghana",
    "GI": "Gibraltar",
    "GL": "Greenland",
    "GM": "Gambia",
    "GN": "Guinea",
    "GP": "Guadeloupe",
    "GQ": "Equatorial Guinea",
    "GR": "Greece",
    "GS": "South Georgia & South Sandwich Islands",
    "GT": "Guatemala",
    "GU": "Guam",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HK": "Hong Kong SAR China",
    "HM": "Heard & McDonald Islands",
    "HN": "Honduras",
    "HR": "Croatia",
    "HT": "Haiti",
    "HU": "Hungary",
    "ID": "Indonesia",
    "IE": "Ireland",
    "IL": "Israel",
    "IM": "Isle of Man",
    "IN": "India",
    "IO": "British Indian Ocean Territory",
    "IQ": "Iraq",
    "IR": "Iran",
    "IS": "Iceland",
    "IT": "Italy",
    "JE": "Jersey",
    "JM": "Jamaica",
    "JO": "Jordan",
    "JP": "Japan",
    "KE": "Kenya",
    "KG": "Kyrgyzstan",
    "KH": "Cambodia",
    "KI": "Kiribati",
    "KM": "Comoros",
    "KN": "St. Kitts & Nevis",
    "KP": "North Korea",
    "KR": "South Korea",
    "KW": "Kuwait",
    "KY": "Cayman Islands",
    "KZ": "Kazakhstan",
    "LA": "Laos",
    "LB": "Lebanon",
    "LC": "St. Lucia",
    "LI": "Liechtenstein",
    "LK": "Sri Lanka",
    "LR": "Liberia",
    "LS": "Lesotho",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "LY": "Libya",
    "MA": "Morocco",
    "MC": "Monaco",
    "MD": "Moldova",
    "ME": "Montenegro",
    "MF": "St. Martin",
    "MG": "Madagascar",
    "MH": "Marshall Islands",
    "MK": "North Macedonia",
    "ML": "Mali",
    "MM": "Myanmar (Burma)",
    "MN": "Mongolia",
    "MO": "Macao SAR China",
    "MP": "Northern Mariana Islands",
    "MQ": "Martinique",
    "MR": "Mauritania",
    "MS": "Montserrat",
    "MT": "Malta",
    "MU": "Mauritius",
    "MV": "Maldives",
    "MW": "Malawi",
    "MX": "Mexico",
    "MY": "Malaysia",
    "MZ": "Mozambique",
    "NA": "Namibia",
    "NC": "New Caledonia",
    "NE": "Niger",
    "NF": "Norfolk Island",
    "NG": "Nigeria",
    "NI": "Nicaragua",
    "NL": "Netherlands",
    "NO": "Norway",
    "NP": "Nepal",
    "NR": "Nauru",
    "NU": "Niue",
    "NZ": "New Zealand",
    "OM": "Oman",
    "PA": "Panama",
    "PE": "Peru",
    "PF": "French Polynesia",
    "PG": "Papua New Guinea",
    "PH": "Philippines",
    "PK": "Pakistan",
    "PL": "Poland",
    "PM": "St. Pierre & Miquelon",
    "PN": "Pitcairn Islands",
    "PR": "Puerto Rico",
    "PS": "Palestinian Territories",
    "PT": "Portugal",
    "PW": "Palau",
    "PY": "Paraguay",
    "QA": "Qatar",
    "RE": "Réunion",
    "RO": "Romania",
    "RS": "Serbia",
    "RU": "Russia",
    "RW": "Rwanda",
    "SA": "Saudi Arabia",
    "SB": "Solomon Islands",
    "SC": "Seychelles",
    "SD": "Sudan",
    "SE": "Sweden",
    "SG": "Singapore",
    "SH": "St. Helena",
    "SI": "Slovenia",
    "SJ": "Svalbard & Jan Mayen",
    "SK": "Slovakia",
    "SL": "Sierra Leone",
    "SM": "San Marino",
    "SN": "Senegal",
    "SO": "Somalia",
    "SR": "Suriname",
    "SS": "South Sudan",
    "ST": "São Tomé & Príncipe",
    "SV": "El Salvador",
    "SX": "Sint Maarten",
    "SY": "Syria",
    "SZ": "Eswatini",
    "TC": "Turks & Caicos Islands",
    "TD": "Chad",
    "TF": "French Southern Territories",
    "TG": "Togo",
    "TH": "Thailand",
    "TJ": "Tajikistan",
    "TK": "Tokelau",
    "TL": "Timor-Leste",
    "TM": "Turkmenistan",
    "TN": "Tunisia",
    "TO": "Tonga",
    "TR": "Türkiye",
    "TT": "Trinidad & Tobago",
    "TV": "Tuvalu",
    "TW": "Taiwan",
    "TZ": "Tanzania",
    "UA": "Ukraine",
    "UG": "Uganda",
    "UM": "U.S. Outlying Islands",
    "US": "United States",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VA": "Vatican City",
    "VC": "St. Vincent & Grenadines",
    "VE": "Venezuela",
    "VG": "British Virgin Islands",
    "VI": "U.S. Virgin Islands",
    "VN": "Vietnam",
    "VU": "Vanuatu",
    "WF": "Wallis & Futuna",
    "WS": "Samoa",
    "YE": "Yemen",
    "YT": "Mayotte",
    "ZA": "South Africa",
    "ZM": "Zambia",
    "ZW": "Zimbabwe",
}

REGIONAL_OFFICES: dict[str, str] = {
    "EM": "European Union (EUIPO)",
    "WO": "WIPO international",
    "EP": "European Patent Office",
}

FILING_JURISDICTIONS: dict[str, str] = {**COUNTRY_NAMES, **REGIONAL_OFFICES}

_ALIASES: dict[str, str] = {
    "uk": "GB",
    "great britain": "GB",
    "britain": "GB",
    "england": "GB",
    "united kingdom of great britain and northern ireland": "GB",
    "usa": "US",
    "united states of america": "US",
    "america": "US",
    "eu": "EM",
    "euipo": "EM",
    "ohim": "EM",
    "european union": "EM",
    "wipo": "WO",
    "pct": "WO",
    "international bureau": "WO",
    "epo": "EP",
    "uae": "AE",
    "turkey": "TR",
    "korea": "KR",
    "republic of korea": "KR",
    "hong kong": "HK",
    "macau": "MO",
    "macao": "MO",
    "czech republic": "CZ",
    "ivory coast": "CI",
    "holland": "NL",
    "burma": "MM",
    "swaziland": "SZ",
    "macedonia": "MK",
    "russian federation": "RU",
    "viet nam": "VN",
}


def _key(value: str) -> str:
    folded = value.casefold().replace("&", " and ").replace("’", "'")
    folded = re.sub(r"[.]", "", folded)
    return re.sub(r"\s+", " ", folded).strip()


_BY_NAME: dict[str, str] = {
    **{_key(name): code for code, name in FILING_JURISDICTIONS.items()},
    **_ALIASES,
}


#: ISO codes that, in an Indian practice's free-text jurisdiction list, more
#: often name a state or union territory (vehicle and ISO 3166-2:IN codes) or
#: the Supreme Court ("SC") than the country: "MH" is Maharashtra before it is
#: the Marshall Islands. On a counsel profile such a bare code is not read as a
#: filing jurisdiction; the country name must be written out ("Switzerland",
#: not "CH"). A filing target is always a code chosen from the picker, so the
#: target side is unaffected.
INDIAN_ABBREVIATION_CODES: frozenset[str] = frozenset(
    {
        "AR", "AS", "BR", "CG", "CH", "GA", "HR", "LA", "MH", "ML",
        "MN", "MP", "MZ", "NL", "PY", "SC", "SK", "TG", "TN", "TR",
    }
)


def canonical_filing_jurisdiction(value: str | None) -> str | None:
    """Return the canonical code for a filing target: a code, name or alias."""

    if not value:
        return None
    stripped = value.strip()
    if stripped.upper() in FILING_JURISDICTIONS:
        return stripped.upper()
    return _BY_NAME.get(_key(stripped))


def profile_filing_jurisdiction(value: str | None) -> str | None:
    """Return the filing jurisdiction one counsel-profile entry names, if any.

    Same as the target vocabulary, except that a bare code that is also an
    Indian state, union territory or court abbreviation names no country.
    """

    if value and value.strip().upper() in INDIAN_ABBREVIATION_CODES:
        return None
    return canonical_filing_jurisdiction(value)


def filing_jurisdiction_matches(target: str, approved: Iterable[str]) -> bool:
    """Whether a profile's jurisdictions cover the filing target.

    Both sides are normalized to the canonical code (the profile side through
    profile_filing_jurisdiction). A target outside the vocabulary (only
    possible for instructions stored before normalization) keeps the
    historical case-insensitive exact comparison so those instructions can
    still be approved, dispatched or reassigned.
    """

    code = canonical_filing_jurisdiction(target)
    values = list(approved)
    if code is None:
        folded = target.strip().casefold()
        return any(value.strip().casefold() == folded for value in values)
    return any(profile_filing_jurisdiction(value) == code for value in values)


def filing_jurisdiction_label(code: str) -> str:
    name = FILING_JURISDICTIONS.get(code)
    return f"{code} · {name}" if name else code


__all__ = [
    "FILING_JURISDICTIONS",
    "INDIAN_ABBREVIATION_CODES",
    "canonical_filing_jurisdiction",
    "filing_jurisdiction_label",
    "filing_jurisdiction_matches",
    "profile_filing_jurisdiction",
]
