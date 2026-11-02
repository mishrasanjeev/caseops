/**
 * Canonical IP jurisdiction vocabulary: ISO-3166 alpha-2 plus EM, WO and EP.
 *
 * Mirrors apps/api/src/caseops_api/core/jurisdictions.py (the API is the
 * authority; apps/api/tests/test_ip_jurisdictions.py checks the two agree), so
 * the form refuses "Narnia" at the field and turns "India" into IN before the
 * request, exactly as the API would.
 */

export const ISO_3166_ALPHA_2 = (
  "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM "
  + "BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX "
  + "CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG "
  + "GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR "
  + "IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV "
  + "LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE "
  + "NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO "
  + "RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF "
  + "TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF "
  + "WS YE YT ZA ZM ZW"
).split(" ");

/** EU trade marks (EUIPO), WIPO international registrations, European patents. */
export const REGIONAL_CODES = ["EM", "WO", "EP"];

const CODES = new Set([...ISO_3166_ALPHA_2, ...REGIONAL_CODES]);

/** Names lawyers commonly type, keyed by upper-cased, space-collapsed text. */
export const JURISDICTION_ALIASES: Record<string, string> = {
  INDIA: "IN",
  UK: "GB",
  "UNITED KINGDOM": "GB",
  "GREAT BRITAIN": "GB",
  USA: "US",
  "UNITED STATES": "US",
  "UNITED STATES OF AMERICA": "US",
  CHINA: "CN",
  JAPAN: "JP",
  SINGAPORE: "SG",
  AUSTRALIA: "AU",
  CANADA: "CA",
  GERMANY: "DE",
  FRANCE: "FR",
  UAE: "AE",
  "UNITED ARAB EMIRATES": "AE",
  EU: "EM",
  EUIPO: "EM",
  "EUROPEAN UNION": "EM",
  WIPO: "WO",
  MADRID: "WO",
  INTERNATIONAL: "WO",
  EPO: "EP",
  "EUROPEAN PATENT OFFICE": "EP",
};

export const JURISDICTION_HINT =
  "Use a two-letter country code (for example IN for India), EM for EU trade marks, WO for international registrations or EP for European patents.";

/** The canonical code for a typed jurisdiction, or null when unknown. */
export function canonicalJurisdiction(value: string): string | null {
  const key = value.trim().toUpperCase().split(/\s+/).filter(Boolean).join(" ");
  const code = JURISDICTION_ALIASES[key] ?? key;
  return CODES.has(code) ? code : null;
}

/** Split typed jurisdictions (comma, semicolon or newline) into codes, naming every unknown token. */
export function parseJurisdictions(value: string): { codes: string[]; error: string | null } {
  const codes: string[] = [];
  const unknown: string[] = [];
  for (const token of value.split(/[,;\n]/).map((item) => item.trim()).filter(Boolean)) {
    const code = canonicalJurisdiction(token);
    if (code === null) unknown.push(token);
    else if (!codes.includes(code)) codes.push(code);
  }
  if (unknown.length === 0) return { codes, error: null };
  const names = unknown.map((item) => `"${item}"`).join(", ");
  const verb = unknown.length === 1 ? "is not a recognised jurisdiction" : "are not recognised jurisdictions";
  return { codes, error: `${names} ${verb}. ${JURISDICTION_HINT}` };
}
