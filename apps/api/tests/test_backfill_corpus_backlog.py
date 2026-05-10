from __future__ import annotations

from caseops_api.scripts import backfill_corpus_backlog as mod


def test_claim_sql_uses_skip_locked_and_priority_order() -> None:
    sql = mod._claim_sql()

    assert "FOR UPDATE OF d SKIP LOCKED" in sql
    assert "structured_version IS NULL OR d.structured_version < :target_version" in sql
    assert "sc-2024" in sql
    assert "delhi-hc-2024" in sql
    assert "ORDER BY c.priority_rank ASC" in sql


def test_claim_sql_excludes_known_non_english_and_ocr_poison() -> None:
    sql = mod._claim_sql()

    assert "source_reference" in sql
    assert ":non_en_suffix" in sql
    assert ":indic_re" in sql
    assert ":cid_re" in sql
    assert "substring(coalesce(d.document_text, '') from 1 for 2000)" in sql


def test_priority_buckets_match_requested_order() -> None:
    labels = [bucket[3] for bucket in mod.PRIORITY_BUCKETS]

    assert labels[:6] == [
        "sc-2024",
        "sc-2023",
        "sc-2022",
        "delhi-hc-2024",
        "delhi-hc-2023",
        "delhi-hc-2022",
    ]
    assert labels[-4:] == [
        "bombay-hc-2023",
        "karnataka-hc-2023",
        "madras-hc-2023",
        "telangana-hc-2023",
    ]
