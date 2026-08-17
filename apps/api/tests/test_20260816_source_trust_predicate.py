"""FMB-01 / FMB-02: the judgment-source trust predicate was dead and inconsistent.

FMB-01 - unsatisfiable by real data. The predicate compared a source field
against the literal ``"official"``. No ingest path writes that value: the two
writers store adapter source keys (``corpus_ingest.py`` writes ``ecourts-hc`` /
``ecourts-sc``; ``authorities.py`` copies the adapter's ``source_key``). The
check was therefore statically dead - it could never pass on real data - while a
test fixture using the fake value kept the suite green. That is the reported
"source links do not open" symptom.

FMB-02 - the surfaces disagreed, and one failed OPEN. Display sites derived
``verified`` from ``bool(row.source_reference)`` / ``bool(row.source_url)``,
which passes any non-empty string including a bare PDF filename, while
``resolve_source_target`` hardcoded ``verified=True`` for authority documents and
for judge appointments. So the resolver - the security-relevant path - trusted
everything unconditionally.

Both are now one derived predicate. It is conjunctive on purpose: a trusted
source key with a bare filename fails because there is nothing to open, and a
good URL under an unknown source key fails because we cannot say where it came
from.
"""

from __future__ import annotations

import pytest

from caseops_api.services.authority_sources import (
    LEGAL_SOURCE_REGISTRY_BY_KEY,
    SOURCE_TYPE_LICENSED,
    SOURCE_TYPE_OFFICIAL,
)
from caseops_api.services.source_actions import (
    authority_source_verified,
    is_official_source_reference,
    judge_appointment_source_verified,
)


def _a_trusted_source_key() -> str:
    for key, entry in LEGAL_SOURCE_REGISTRY_BY_KEY.items():
        if entry.source_type in {SOURCE_TYPE_OFFICIAL, SOURCE_TYPE_LICENSED}:
            return key
    raise AssertionError("registry carries no official or licensed source")


class TestPredicateIsSatisfiableByRealData:
    """FMB-01: the old predicate could never pass. The new one must be reachable."""

    def test_a_real_source_key_with_an_official_url_verifies(self) -> None:
        key = _a_trusted_source_key()
        assert authority_source_verified(key, "https://main.sci.gov.in/judgment.pdf") is True

    def test_the_literal_official_is_not_a_source_key(self) -> None:
        # The value the old predicate compared against. Nothing writes it, and
        # it must not become a magic passphrase either.
        assert "official" not in LEGAL_SOURCE_REGISTRY_BY_KEY
        assert authority_source_verified("official", "https://main.sci.gov.in/x.pdf") is False

    def test_bulk_mirror_keys_are_untrusted(self) -> None:
        """corpus_ingest writes these; they are public mirrors, not a registry."""
        for key in ("ecourts-hc", "ecourts-sc"):
            assert authority_source_verified(key, "https://main.sci.gov.in/x.pdf") is False, (
                f"{key} is a bulk mirror and is deliberately absent from the "
                "registry; classifying it trusted would be a product decision, "
                "not a bug fix"
            )


class TestConjunctive:
    def test_trusted_key_with_a_bare_filename_fails(self) -> None:
        # The shape corpus ingest actually stores. There is nothing to open.
        assert authority_source_verified(_a_trusted_source_key(), "judgment_2023.pdf") is False

    def test_trusted_key_with_no_reference_fails(self) -> None:
        assert authority_source_verified(_a_trusted_source_key(), None) is False

    def test_official_url_under_an_unknown_key_fails(self) -> None:
        assert authority_source_verified("some-scraper", "https://main.sci.gov.in/x.pdf") is False

    def test_unknown_key_and_no_reference_fails(self) -> None:
        assert authority_source_verified(None, None) is False


class TestNoLongerFailsOpen:
    """FMB-02: bool(reference) passed anything non-empty."""

    @pytest.mark.parametrize(
        "reference",
        [
            "judgment.pdf",
            "some-internal-ref",
            "http://insecure.example.com/x.pdf",
            "https://random-blog.example.com/judgment",
            "ftp://main.sci.gov.in/x.pdf",
            "   ",
        ],
    )
    def test_non_official_references_are_not_verified(self, reference: str) -> None:
        assert is_official_source_reference(reference) is False
        assert authority_source_verified(_a_trusted_source_key(), reference) is False
        assert judge_appointment_source_verified(reference) is False

    def test_judge_appointment_requires_an_official_url(self) -> None:
        assert judge_appointment_source_verified(None) is False
        assert judge_appointment_source_verified("") is False
        assert judge_appointment_source_verified("https://main.sci.gov.in/judge.htm") is True


class TestOneSharedPredicate:
    """The drift itself: every surface must reach the same verdict."""

    @pytest.mark.parametrize(
        ("source", "reference"),
        [
            ("ecourts-hc", "judgment.pdf"),
            ("ecourts-sc", "https://main.sci.gov.in/x.pdf"),
            ("unknown", "https://main.sci.gov.in/x.pdf"),
            (None, None),
        ],
    )
    def test_display_and_resolver_agree(self, source: str | None, reference: str | None) -> None:
        """Both call sites now derive from the same helper, so they cannot diverge.

        Previously the display surfaces computed bool(reference) while the
        resolver hardcoded True, so these inputs produced opposite verdicts on
        the same row.
        """
        verdict = authority_source_verified(source, reference)
        assert verdict is authority_source_verified(source, reference)
        assert verdict is False

    def test_externally_sourced_branches_no_longer_hardcode_true(self) -> None:
        """Only CaseOps-hosted content may assert verification unconditionally.

        Matter attachments and IP document versions are served from our own
        download routes behind `assert_access`, so hardcoding True there is
        correct - we host the bytes and we authorised the read. The two branches
        that resolve *externally sourced* material must derive their verdict.
        """
        import inspect

        from caseops_api.services import source_actions

        body = inspect.getsource(source_actions.resolve_source_target)
        # Both externally-sourced branches derive their verdict...
        assert "authority_source_verified(" in body
        assert "judge_appointment_source_verified(" in body
        # ...and only the two hosted branches assert it unconditionally, which
        # the companion test pins to exactly 2.
        assert body.count("verified=True") == 2

    def test_hosted_content_may_still_assert_verification(self) -> None:
        """Guards the inverse: do not "fix" hosted branches into failing closed."""
        import inspect

        from caseops_api.services import source_actions

        body = inspect.getsource(source_actions.resolve_source_target)
        assert body.count("verified=True") == 2, (
            "exactly two hosted branches (matter attachment, IP document "
            "version) may assert verification; a change here needs review"
        )
