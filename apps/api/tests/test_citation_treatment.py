"""Tests for the citation-treatment classifier (PG-006 Phase 1A).

The classifier reads cue verbs in the ±200-char window around a
citation and maps them to one of eight treatments. These tests
anchor each tier on a representative cue and confirm the neutral
fallback fires when no cue is present.
"""
from __future__ import annotations

from caseops_api.db.models import AuthorityCitationTreatment
from caseops_api.services.citation_treatment import (
    CONTEXT_WINDOW_CHARS,
    classify_citation_treatment,
)

# ---------- Single-cue happy path per treatment tier ----------


def test_overruled_explicit() -> None:
    body = (
        "The view taken in (2010) 4 SCC 100 stands overruled by the "
        "Constitution Bench in the present case."
    )
    res = classify_citation_treatment(body, "(2010) 4 SCC 100")
    assert res.treatment == AuthorityCitationTreatment.OVERRULED
    assert res.confidence > 0
    assert res.evidence_text is not None
    assert "overruled" in res.evidence_text.lower()


def test_reversed_appeal() -> None:
    body = (
        "The judgment in AIR 2015 Del 99 is reversed in appeal and the "
        "writ petition is allowed."
    )
    res = classify_citation_treatment(body, "AIR 2015 Del 99")
    assert res.treatment == AuthorityCitationTreatment.REVERSED
    assert res.confidence > 0


def test_doubted_correctness() -> None:
    body = (
        "We doubt the correctness of the principle laid down in "
        "(2012) 3 SCC 45 and refer the matter to a larger Bench."
    )
    res = classify_citation_treatment(body, "(2012) 3 SCC 45")
    assert res.treatment == AuthorityCitationTreatment.DOUBTED


def test_distinguished_on_facts() -> None:
    body = (
        "The decision in (2017) 11 SCC 200 is distinguished on the "
        "facts of the present case as the parties stand differently."
    )
    res = classify_citation_treatment(body, "(2017) 11 SCC 200")
    assert res.treatment == AuthorityCitationTreatment.DISTINGUISHED


def test_dissented_only() -> None:
    body = (
        "Reliance was placed on (2019) 8 SCC 78 in the dissenting "
        "opinion of Pardiwala, J."
    )
    res = classify_citation_treatment(body, "(2019) 8 SCC 78")
    assert res.treatment == AuthorityCitationTreatment.DISSENTED


def test_followed_with_approval() -> None:
    body = (
        "We respectfully agree with and follow (2018) 6 SCC 1, which "
        "settled the question of jurisdiction conclusively."
    )
    res = classify_citation_treatment(body, "(2018) 6 SCC 1")
    assert res.treatment == AuthorityCitationTreatment.FOLLOWED


def test_considered_weak() -> None:
    body = (
        "The Bench considered (2014) 2 SCC 333 in passing but did not "
        "find it directly applicable to the issue at hand."
    )
    res = classify_citation_treatment(body, "(2014) 2 SCC 333")
    assert res.treatment == AuthorityCitationTreatment.CONSIDERED


def test_neutral_when_no_cue() -> None:
    body = (
        "The petitioner refers to (2020) 7 SCC 50 in support of the "
        "general proposition."
    )
    res = classify_citation_treatment(body, "(2020) 7 SCC 50")
    assert res.treatment == AuthorityCitationTreatment.NEUTRAL
    assert res.confidence == 0
    assert res.evidence_text is None


# ---------- Confidence + evidence shape ----------


def test_confidence_rises_with_multiple_cues() -> None:
    """Two cues in the same window should produce strong confidence."""
    body = (
        "The proposition in (2015) 9 SCC 11 is overruled and no longer "
        "good law in light of the present Constitution Bench."
    )
    res = classify_citation_treatment(body, "(2015) 9 SCC 11")
    assert res.treatment == AuthorityCitationTreatment.OVERRULED
    # "overruled" + "no longer good law" both fire = 2 cues = ~0.85.
    assert res.confidence >= 0.8


def test_evidence_snippet_within_500_chars() -> None:
    body = (
        "The proposition stands overruled by the present case. "
        "(2010) 4 SCC 100 is therefore no longer binding."
    )
    res = classify_citation_treatment(body, "(2010) 4 SCC 100")
    assert res.evidence_text is not None
    assert len(res.evidence_text) <= 500


# ---------- Tier priority ----------


def test_overrule_beats_followed_when_both_in_window() -> None:
    """If a window has 'followed' AND 'overruled', the bad-law signal
    must win — losing it to a softer cue would mislead the lawyer."""
    body = (
        "Although (2010) 4 SCC 100 was followed in earlier benches, it "
        "is overruled today and the appellant's argument fails."
    )
    res = classify_citation_treatment(body, "(2010) 4 SCC 100")
    assert res.treatment == AuthorityCitationTreatment.OVERRULED


def test_reversed_beats_distinguished() -> None:
    body = (
        "The order in AIR 2015 Del 99 is reversed in appeal; the "
        "facts were also distinguishable."
    )
    res = classify_citation_treatment(body, "AIR 2015 Del 99")
    assert res.treatment == AuthorityCitationTreatment.REVERSED


# ---------- Edge cases ----------


def test_empty_inputs_neutral() -> None:
    assert (
        classify_citation_treatment("", "(2010) 4 SCC 100").treatment
        == AuthorityCitationTreatment.NEUTRAL
    )
    assert (
        classify_citation_treatment("body text", "").treatment
        == AuthorityCitationTreatment.NEUTRAL
    )


def test_citation_not_in_text_neutral() -> None:
    """If the literal citation_text doesn't appear in document_text the
    classifier returns neutral instead of crashing."""
    body = "This text refers to (2018) 6 SCC 1."
    res = classify_citation_treatment(body, "AIR 2020 SC 999")
    assert res.treatment == AuthorityCitationTreatment.NEUTRAL


def test_window_bounded() -> None:
    """A cue verb 1000 chars before the citation must NOT fire."""
    body = (
        "The earlier authorities were overruled long ago. "
        + ("padding sentence. " * 80)
        + "(2018) 6 SCC 1 is therefore the leading case."
    )
    # Window is 200 chars on each side; the "overruled" sits well
    # outside that window, so this should classify neutral, not
    # overruled.
    assert (
        len(body) > CONTEXT_WINDOW_CHARS * 2
    )  # sanity-check the test fixture
    res = classify_citation_treatment(body, "(2018) 6 SCC 1")
    assert res.treatment == AuthorityCitationTreatment.NEUTRAL


def test_case_insensitive() -> None:
    body = "Reaffirmed in (2020) 7 SCC 50, the rule applies."
    res = classify_citation_treatment(body, "(2020) 7 SCC 50")
    assert res.treatment == AuthorityCitationTreatment.FOLLOWED
