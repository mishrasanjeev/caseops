/** Reviewed public references, not a registry adapter or a legal-rule activation. */
export const IPINDIA_REVIEWED_ON = "2026-11-14";
export type IpIndiaSourceKind = "register" | "form" | "rule";
export type IpIndiaSource = {
  id: string;
  domain: "patent" | "trademark" | "design";
  kind: IpIndiaSourceKind;
  title: string;
  url: string;
  discoveredFrom: string;
  summary: string;
  fields: readonly string[];
  access: string;
  sha256?: string;
};

const gateways = "https://ipindia.gov.in/pages/e-services";
const patentForms = "https://www.ipindia.gov.in/patents-before-you-apply-forms-official-fees";

export const IPINDIA_SOURCES: readonly IpIndiaSource[] = [
  {
    id: "patent-register", domain: "patent", kind: "register", title: "IP India patent public search",
    url: "https://iprsearch.ipindia.gov.in/publicsearch", discoveredFrom: gateways,
    summary: "Search published or granted patents on the official portal with field, date and logical-operator controls.",
    fields: [], access: "External portal; CAPTCHA required. No register records are imported by this reference search.",
  },
  {
    id: "trademark-register", domain: "trademark", kind: "register", title: "IP India trademark public search",
    url: "https://tmrsearch.ipindia.gov.in/tmrpublicsearch/", discoveredFrom: gateways,
    summary: "Official trademark search portal, separate from CaseOps recorded trademark dockets and journal evidence.",
    fields: [], access: "External portal; OTP and CAPTCHA were required when reviewed. No automatic search or synchronization.",
  },
  {
    id: "design-register", domain: "design", kind: "register", title: "IP India design public search",
    url: "https://search.ipindia.gov.in/designsearch", discoveredFrom: gateways,
    summary: "Official design-search portal. CaseOps does not import its register through these references.",
    fields: [], access: "External portal; complete its current access checks there. No automated register access is enabled.",
  },
  {
    id: "patent-form-2", domain: "patent", kind: "form", title: "Patent Form 2: provisional / complete specification",
    url: "https://www.ipindia.gov.in/storage/uploads/docs-operator/ee69dc48-77c4-4900-b222-154573143a4f.pdf",
    discoveredFrom: patentForms,
    summary: "Field summary transcribed from the official one-page image PDF. Provisional and complete specifications use different preambles; claims are not applicable to a provisional specification. Description, claims and complete-specification abstract have separate-page directions. This summary is not a completed form or filing validation.",
    fields: ["Invention title", "Applicant name, nationality and address", "Provisional or complete description preamble", "Description", "Claims for complete specification", "Date and signature", "Abstract for complete specification"],
    access: "Official PDF; verify the latest version and applicable requirements before filing.",
    sha256: "b2329c5274d5e7d7f4dc15b2a77233275f0c2bc53873a64466561bbade13fca9",
  },
  {
    id: "patent-rule-13", domain: "patent", kind: "rule", title: "Patent Rule 13: specification requirements",
    url: "https://ipindia.gov.in/acts/patent-rules-2003/rule-13", discoveredFrom: patentForms,
    summary: "The published rule identifies Form 2 for specifications, addresses divisional and patent-of-addition references and drawings, and limits the abstract to 150 words. Check the full rule and applicable amendments; this reference does not approve a draft or activate a deadline.",
    fields: [], access: "Official rule page reviewed on the stated date, not a certification of current-law completeness.",
  },
  {
    id: "trademark-forms", domain: "trademark", kind: "form", title: "Trademark forms and official fees: TM-A, TM-O, TM-R",
    url: "https://www.ipindia.gov.in/pages/trade-marks/learn/forms-and-official-fees", discoveredFrom: gateways,
    summary: "Official index links TM-A registration, TM-O opposition and related proceedings, and TM-R renewal forms. Fee amounts depend on the filing and applicant; no fee is calculated or frozen here.",
    fields: [], access: "Form index only; no downloaded form contents, filing completion or exhaustive form coverage is claimed.",
  },
  {
    id: "design-forms", domain: "design", kind: "form", title: "Design forms and official fees: Form 1 and search requests",
    url: "https://www.ipindia.gov.in/manual-blocks/forms-and-official-fees", discoveredFrom: gateways,
    summary: "Official index lists Form 1 for design registration and Forms 6 and 7 for search requests, alongside other design forms.",
    fields: [], access: "Form index only; no downloaded form contents or completed filing is claimed.",
  },
];

export function searchIpIndiaSources(query: string, kind: "all" | IpIndiaSourceKind = "all"): readonly IpIndiaSource[] {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return IPINDIA_SOURCES.filter((row) => (kind === "all" || row.kind === kind)
    && terms.every((term) => [row.title, row.domain, row.summary, ...row.fields].join(" ").toLowerCase().includes(term)));
}
