from __future__ import annotations

from caseops_api.services.activity_reports import render_report


def _report() -> dict:
    return {
        "generated_at": "2026-07-10T08:00:00+05:30",
        "reporting_periods": {
            "day": {"start_date": "2026-07-09", "end_date": "2026-07-09"},
            "week": {"start_date": "2026-06-29", "end_date": "2026-07-05"},
            "month": {"start_date": "2026-06-01", "end_date": "2026-06-30"},
        },
        "segments": {
            "law_firms": {
                "company_count": 2,
                "company_names": ["Alpha Legal", "Beta & Partners"],
                "periods": {
                    "day": {"matters_created": 12, "notices_sent": 3},
                    "week": {"matters_created": 45, "notices_sent": 9},
                    "month": {"matters_created": 1234, "notices_sent": 27},
                },
            },
            "general_counsels": {
                "company_count": 1,
                "company_names": ["Example Industries"],
                "periods": {
                    "day": {"matters_created": 2, "notices_sent": 1},
                    "week": {"matters_created": 8, "notices_sent": 4},
                    "month": {"matters_created": 31, "notices_sent": 11},
                },
            },
        },
    }


def test_render_report_builds_readable_html_and_plaintext_tables() -> None:
    text, html = render_report(_report())

    assert "<!doctype html>" in html
    assert '<table role="presentation"' in html
    assert '<th scope="col">Daily' in html
    assert '<th scope="row">Matters created</th>' in html
    assert '<th scope="row">Notices sent</th>' in html
    assert "09 Jul 2026" in html
    assert "29 Jun 2026 - 05 Jul 2026" in html
    assert ">1,234</td>" in html
    assert "Law Firms" in html
    assert "General Counsels" in html
    assert "Alpha Legal" in html
    assert "Beta &amp; Partners" in html
    assert "border-collapse" in html
    assert "@media(max-width:620px)" in html

    assert "Metric                   Daily      Weekly     Monthly" in text
    assert "Matters created" in text
    assert "1,234" in text
    assert "Daily: 09 Jul 2026" in text
    assert "- Beta & Partners" in text


def test_render_report_escapes_names_and_handles_empty_directory() -> None:
    report = _report()
    report["segments"]["law_firms"]["company_names"] = ["A&B <Legal>"]
    report["segments"]["general_counsels"]["company_count"] = 0
    report["segments"]["general_counsels"]["company_names"] = []

    text, html = render_report(report)

    assert "A&amp;B &lt;Legal&gt;" in html
    assert "A&B <Legal>" not in html
    assert "A&B <Legal>" in text
    assert "No companies recorded" in html
    assert "Company directory (0)" in html
    assert "- None" in text
