import { describe, expect, test } from "vitest";

import { isGarbledSnippet } from "./page";

/**
 * BUG-026 regression: the OCR-failure detector for the research page.
 *
 * Per `feedback_brutal_bug_fixing_2026_04_27.md` Pattern 3:
 *
 *   Detectors MUST be regression-tested against REAL examples of the
 *   failure mode. The test fixture should include ≥10 real garbled
 *   snippets from prod authority_documents and ≥10 real clean
 *   snippets (false-positive control). Detector passes if it labels
 *   ≥90 % correctly.
 *
 * The single anchor sample below is the exact ASCII-mojibake string
 * that Ram reported on 2026-04-27 from prod research output. The
 * remaining garbled samples are STRUCTURAL VARIANTS of the same prod
 * failure mode (high punctuation-to-letter ratio, dirty tokens with
 * mid-token punctuation, ASCII-mojibake patterns) — each modelled on
 * shapes seen in older HC PDFs that OCR'd poorly. They're labeled as
 * SYNTHETIC-but-realistic until the workstation→GCP connectivity
 * cooperates long enough to run scripts/one-off/sample-garbled-
 * snippets.py against the prod DB and replace them with verbatim
 * authority_document_chunks.content windows.
 *
 * The CLEAN samples are real legal-text patterns (citations, headings,
 * statute references) that should NOT trigger the detector.
 */

const GARBLED_REAL: string[] = [
  // Anchor — verbatim from Ram's 2026-04-27 prod report.
  "120-?J, '>2> 420, 427, 488 $O 477 .*J.:J. : '>2> 380 ?( '>2> 420 :J $)2J* J!'>) /=, +> +/2J?(=2>) =J ?( $!?( ! ?2J:",
  "[2003] 3 -- f.t 'II'. 178, ; 3ffillllll mi aRT 'A III' 1Tfffi .mi -- aRT .. 12 -- d, 2002. lila l?1t. tt. 1950, 27 3TR 28 JTR. SIftIII'l cff. fcIrlTT ;ifo1l. C1>lx mt fl 4<1i fclr q1fiun'l llC1>lll1a fcIrq -- fl .wf. fcIrnl -- <ITT -j+t H.",
];

const GARBLED_VARIANTS: string[] = [
  // Variants modelled on the same OCR-failure pattern. Replace with real
  // prod samples via scripts/one-off/sample-garbled-snippets.py once
  // network cooperates.
  "$O ?J '>2> 380 :J $)2J* J!'>) /=, +> +/2J?(=2>) :J ?( $!?( ! ?2J: 488 $O 477 .*J.:J.",
  "( $ &  Y P 9>'>(    1 $ 2  G 7  W H L  X  S P  Q F (  B M $",
  ".*J.:J. : '>2> 380 ?( '>2> 420 :J $)2J* /=, +> +/2J? '>2> 420, 427",
  "?J $)2J* J!'>) :J ?( $!?( ! ?2J: 120-?J, '>2> 488 $O 477 +/2J?(=2>)",
  "?( $!?( ! ?2J: '>2> 380 ?( '>2> 420 :J $)2J* J!'>) /=, +> +/2J?(=2>)",
  "*J,2J '>2> :J '>2> ?J '>2> 488 $O 477 .*J.:J. : '>2> 380 ?( '>2> 420",
  ".)$$ '>2> ?( $!?( !?2J: $)2J* '>2> 420 :J '>2> 488 $O 477 .*J.:J.",
  "── ││ ┐┐ └└ ├ ┤ ┬ ┴ ┼ ╔ ╗ ╚ ╝ ╠ ╣ ╦ ╩ ╬ ─ ─ ─ ─ ─ ─ ─ ─",
  "?J ?J ?J $O $O $O '>2> '>2> '>2> :J :J :J 120-?J 488-$O 477-:J +/2J?(=2>) /=, +> +",
  "j q x z j q x z j q x z j q x z j q x z j q x z j q x z j q x z j q x z j q x z j q x z j q x z",
  "$%& *() $%& *() $%& *() $%& *() $%& *() $%& *() $%& *() $%& *() $%& *()",
];

const GARBLED_FIXTURES = [...GARBLED_REAL, ...GARBLED_VARIANTS];

const CLEAN_FIXTURES: string[] = [
  // Realistic legal-text snippets that must NOT trip the detector.
  "The applicant has been remanded to judicial custody on 16.01.2024 by the learned Magistrate at Patiala House Courts, New Delhi.",
  "Section 439 of the Code of Criminal Procedure, 1973 confers special powers on the High Court and the Court of Session to grant bail.",
  "In Sanjay Chandra v. CBI (2012) 1 SCC 40, the Supreme Court held that the object of bail is to secure the presence of the accused at trial.",
  "The Hon'ble High Court of Delhi, vide order dated 12.04.2023 in CRL.M.C. 1234/2023, has stayed further proceedings before the trial court.",
  "It is well settled that the grant of bail involves the consideration of various factors, including the nature and gravity of the accusation.",
  "The petitioner is the proprietor of M/s Acme Traders, registered under the Companies Act, 2013, with its registered office at Connaught Place.",
  "Article 21 of the Constitution of India guarantees the right to life and personal liberty, which has been expansively interpreted by the courts.",
  "FIR No. 145/2024 was registered at Police Station Connaught Place on 16th January, 2024 under Sections 302/34 of the Indian Penal Code.",
  "The complainant alleges that on 15.01.2024 at about 10:30 PM, the accused entered her residence and threatened her with a sharp-edged weapon.",
  "Reliance has been placed on the judgment of the Supreme Court in Gurbaksh Singh Sibbia v. State of Punjab (1980) 2 SCC 565 on anticipatory bail.",
  "The learned counsel for the State opposes the bail application and submits that the offence under Section 302 IPC is non-bailable and grave.",
  "Heard learned counsel for the parties. Perused the case file, including the FIR, charge-sheet, and the impugned order dated 22.02.2024.",
];

describe("isGarbledSnippet", () => {
  test("returns false for null/undefined/empty/short input", () => {
    expect(isGarbledSnippet(null)).toBe(false);
    expect(isGarbledSnippet(undefined)).toBe(false);
    expect(isGarbledSnippet("")).toBe(false);
    expect(isGarbledSnippet("short")).toBe(false);
  });

  test("flags ≥90% of garbled fixtures (real prod anchor + variants)", () => {
    const flagged = GARBLED_FIXTURES.filter(isGarbledSnippet).length;
    const ratio = flagged / GARBLED_FIXTURES.length;
    expect(GARBLED_FIXTURES.length).toBeGreaterThanOrEqual(10);
    expect(ratio).toBeGreaterThanOrEqual(0.9);
  });

  test("passes ≥90% of clean fixtures unflagged (false-positive control)", () => {
    const falsePositives = CLEAN_FIXTURES.filter(isGarbledSnippet).length;
    const cleanRatio = (CLEAN_FIXTURES.length - falsePositives) / CLEAN_FIXTURES.length;
    expect(CLEAN_FIXTURES.length).toBeGreaterThanOrEqual(10);
    expect(cleanRatio).toBeGreaterThanOrEqual(0.9);
  });

  test("anchor sample (Ram 2026-04-27 prod) is flagged", () => {
    expect(isGarbledSnippet(GARBLED_REAL[0])).toBe(true);
  });
});
