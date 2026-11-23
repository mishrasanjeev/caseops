"""Public Trade Marks Journal feed for journal watch (IPLF-052C, UJ-33).

Real journal pages name individual proprietors and their addresses, so no real
page is committed. The fixtures below are synthetic and shaped like the
2026-11-16 journal (No. 2287): the bilingual labels are kept with Latin
placeholders where the Hindi label sits, because the parser keys only on the
English labels. ``CASEOPS_IPINDIA_JOURNAL_SAMPLE`` may point at a locally saved
real journal PDF to run the same parser against it.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from fpdf import FPDF
from sqlalchemy import func, inspect, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingSubscription,
    CompanyMembership,
    IpJournalFeedSetting,
    IpJournalFeedTenantRun,
    IpJournalIngestionRun,
    IpJournalPublication,
    IpPublicJournalCheck,
    IpPublicJournalDocument,
    IpPublicJournalEntry,
    IpWatchHit,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import ip_journal_feed as feed
from caseops_api.services.ip_india_journal_parser import (
    extract_page_texts,
    parse_journal_pages,
)
from caseops_api.services.ip_india_journal_source import (
    LISTING_URL,
    ROBOTS_URL,
    IpIndiaJournalClient,
    JournalSourceError,
    JournalSourceRefused,
    allowed_file_name,
    challenge_reason,
    document_url,
    parse_listing,
)
from tests.test_auth_company import auth_headers
from tests.test_ip_journal_watch import _fixture, _profile

JOURNAL = "2287"
JOURNAL_DATE = date(2026, 11, 16)
NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)
CLASS_FILE = r"ipo-docs\IPIndia_Docs\TMR\2026\2287\Class 1-9.pdf"
MULTI_FILE = r"ipo-docs\IPIndia_Docs\TMR\2026\2287\Multiclass - Notice.pdf"


# --- synthetic journal pages, shaped like the real ones ----------------------


def _entry_lines(
    application: str,
    *,
    proprietor: str = "ASTER RIVAL PRIVATE LIMITED",
    header_class: str = "9",
    goods: tuple[str, ...] = ("Class 9: Downloadable legal software",),
    mark: str | None = "ASTER RIVAL",
    journal: str = JOURNAL,
    journal_date: str = "16/11/2026",
) -> list[str]:
    return [
        f"Avedan sankhya/Application Number: {application}",
        "Avedan ki tithi/Date of Filing:",
        "28-12-2021",
        "Bauddhik sampada bharat",
        "Intellectual PropertyINDIA",
        f"Journal sankhya/Journal Number: {journal}",
        "Journal prakashan tithi/Journal Publication Date:",
        journal_date,
        "TRADE MARKS PUBLICATION DETAILS",
        "Avedan ka vivaran/Application Details:",
        f"Swatvadhari/Avedak/ Proprietor/Applicant {proprietor}",
        "Swatvadhari/Avedak ka pata/",
        "Proprietor/Applicant Address",
        "1 Example Road, Mumbai 400001",
        "Avedak ka prakar / Type of Applicant Body Incorporate",
        f"Varg/Class {header_class}",
        "Vastu ka vivaran/ Description of",
        "Goods/Services",
        *goods,
        "Tab se upyog / Used Since Proposed to be Used",
        "Kshetradhikar / Jurisdiction MUMBAI",
        "Sharten aur pratibandh / Condition And",
        "Restriction",
        "N/A",
        "Vigyapit",
        "vyapar chinh/Advertised Trade Mark",
        *([mark] if mark else []),
    ]


def _page(lines: list[str], printed: int) -> str:
    return "\r\n".join([*lines, str(printed)])


SECTION_HEADER = _page(
    [
        "Trade Marks Journal No: 2287 Date: 16/11/2026",
        "Vyapar chinh vigyapit avedan / ADVERTISED APPLICATIONS",
        "Varg 9",
        "CLASS 9",
    ],
    4283,
)


def _journal_pages() -> list[str]:
    return [
        SECTION_HEADER,
        _page(_entry_lines("9000001"), 4284),
        _page(
            _entry_lines(
                "9000002",
                proprietor="ZEPHYR FOODS LLP",
                header_class="5",
                goods=("Class 5: Dietary supplements",),
                mark=None,  # a device mark: the words are in the image
            ),
            4285,
        ),
        # A long goods description that continues, and the mark on the next page.
        _page(_entry_lines("9000003", mark=None)[:-2], 4286),
        _page(["Vigyapit", "vyapar chinh/Advertised Trade Mark", "ASTER CLOUD"], 4287),
        _page(
            _entry_lines(
                "9000004",
                proprietor="GLOBAL MARKS INC.",
                header_class="99 (Multi-Class / bahu-varg)",
                goods=(
                    "Class 9: Computer software",
                    "Class 42: Software as a service;",
                    "design of computer systems",
                ),
                mark="ZORBIX",
            ),
            4288,
        ),
    ]


def _pdf(pages: list[str]) -> bytes:
    document = FPDF()
    document.set_font("Helvetica", size=9)
    for page in pages:
        document.add_page()
        for line in page.split("\r\n"):
            document.cell(text=line, new_x="LMARGIN", new_y="NEXT")
    return bytes(document.output())


def _listing(files: list[str], *, journal: str = JOURNAL, published: str = "16/11/2026") -> str:
    forms = "".join(
        '<form action="/IPOJournal/Journal/ViewJournal" method="post" target="_blank">'
        f'<input type="hidden" name="FileName" value="{name}" />'
        f'<button type="submit" class="btn btn-link">{name.rsplit(chr(92), 1)[-1]}</button>'
        "</form>"
        for name in files
    )
    return (
        "<html><body><h2><span>Trade Marks Journal</span></h2>"
        '<table id="Journal" class="table"><thead><tr><th>Sr. No.</th><th>Journal No.</th>'
        "<th>Date of Publication</th><th>Date of Availability</th><th>Download</th></tr>"
        f"</thead><tbody><tr><td>1</td><td>{journal}</td><td>{published}</td>"
        f'<td>{published}</td><td class="table-grid">{forms}</td></tr>'
        "<tr><td>2</td><td>2200</td><td>06/01/2025</td><td>06/01/2025</td>"
        '<td><form><input type="hidden" name="FileName" '
        'value="ipo-docs\\IPIndia_Docs\\TMR\\2025\\2200\\CLASS 1 - 31.pdf" /></form></td></tr>'
        "</tbody></table></body></html>"
    )


# --- parser ------------------------------------------------------------------


def test_parser_reads_entries_devices_continuations_and_multi_class() -> None:
    parsed = parse_journal_pages(
        _journal_pages(), journal_number=JOURNAL, journal_date=JOURNAL_DATE
    )
    assert parsed.page_count == 6
    assert parsed.review_count == 0
    rows = {row.application_number: row for row in parsed.entries}
    assert set(rows) == {"9000001", "9000002", "9000003", "9000004"}
    word = rows["9000001"]
    assert (word.status, word.mark_text, word.class_numbers) == ("parsed", "ASTER RIVAL", (9,))
    assert word.proprietor_name == "ASTER RIVAL PRIVATE LIMITED"
    assert word.goods_services == {"9": ["Downloadable legal software"]}
    assert (word.page_start, word.journal_page, word.registry_office) == (2, "4284", "MUMBAI")
    assert word.filing_date == date(2021, 12, 28)
    device = rows["9000002"]
    assert device.status == "parsed" and device.mark_text is None
    continued = rows["9000003"]
    assert (continued.page_start, continued.page_end, continued.mark_text) == (4, 5, "ASTER CLOUD")
    multi = rows["9000004"]
    assert multi.class_numbers == (9, 42)
    assert multi.goods_services["42"] == ["Software as a service; design of computer systems"]


def test_parser_flags_unreliable_or_incomplete_entries_instead_of_dropping_them() -> None:
    hindi_mark = "".join(chr(code) for code in (0x0915, 0x093E, 0x0930))
    pages = [
        _page(["Stray page before any entry", "with no labels"], 10),
        _page(_entry_lines("9000010", mark=hindi_mark), 11),
        _page(_entry_lines("9000011", proprietor="").copy(), 12),
        _page(_entry_lines("9000012", journal="2286"), 13),
        _page(_entry_lines("9000013", header_class="9", goods=("Class 12: Vehicles",)), 14),
    ]
    parsed = parse_journal_pages(pages, journal_number=JOURNAL, journal_date=JOURNAL_DATE)
    reasons = {row.application_number: row.review_reason for row in parsed.entries}
    assert reasons[None] == "pages_outside_any_entry"
    assert reasons["9000010"] == "mark_text_unreliable"
    assert "proprietor_not_recognised" in reasons["9000011"]
    assert reasons["9000012"] == "journal_identity_mismatch"
    assert reasons["9000013"] == "class_mismatch"
    assert parsed.parsed_count == 0
    assert parsed.review_count == len(pages)
    # Every page lands in exactly one row.
    covered = sorted(
        page for row in parsed.entries for page in range(row.page_start, row.page_end + 1)
    )
    assert covered == [1, 2, 3, 4, 5]


def test_parser_flags_a_changed_layout_as_one_review_row() -> None:
    pages = [_page(["CORRIGENDA", "Something the parser does not know"], 1)] * 3
    parsed = parse_journal_pages(pages, journal_number=JOURNAL, journal_date=JOURNAL_DATE)
    rows = [(row.status, row.review_reason, row.page_start, row.page_end) for row in parsed.entries]
    assert rows == [("needs_review", "no_entries_recognised", 1, 3)]


def test_parser_restores_pdfium_line_end_hyphen() -> None:
    goods = ("Class 9: SDI" + chr(0xFFFE), "FORMATTED SIGNALS")
    parsed = parse_journal_pages(
        [_page(_entry_lines("9000020", goods=goods), 1)],
        journal_number=JOURNAL,
        journal_date=JOURNAL_DATE,
    )
    assert parsed.entries[0].status == "parsed"
    assert parsed.entries[0].goods_services == {"9": ["SDI- FORMATTED SIGNALS"]}


def test_pdf_text_extraction_feeds_the_parser() -> None:
    pages = extract_page_texts(_pdf(_journal_pages()))
    assert len(pages) == 6
    parsed = parse_journal_pages(pages, journal_number=JOURNAL, journal_date=JOURNAL_DATE)
    assert parsed.parsed_count == 4 and parsed.review_count == 0


@pytest.mark.skipif(
    not os.environ.get("CASEOPS_IPINDIA_JOURNAL_SAMPLE"),
    reason="Set CASEOPS_IPINDIA_JOURNAL_SAMPLE to a saved Trade Marks Journal 2287 PDF.",
)
def test_parser_on_a_saved_real_journal_pdf() -> None:
    data = Path(os.environ["CASEOPS_IPINDIA_JOURNAL_SAMPLE"]).read_bytes()
    parsed = parse_journal_pages(
        extract_page_texts(data), journal_number=JOURNAL, journal_date=JOURNAL_DATE
    )
    assert parsed.parsed_count > 0
    assert parsed.review_count <= max(1, parsed.parsed_count // 50)
    covered = sum(row.page_end - row.page_start + 1 for row in parsed.entries)
    assert covered >= parsed.page_count - 40  # section headers only are skipped


# --- listing and client -----------------------------------------------------


def test_listing_parser_reads_issues_and_never_builds_file_names() -> None:
    listing = parse_listing(_listing([CLASS_FILE, MULTI_FILE, r"ipo-docs\..\secret.pdf"]))
    assert listing.issues == 2
    recent = [item for item in listing.files if item.journal_number == JOURNAL]
    assert [item.file_name for item in recent] == [
        CLASS_FILE, MULTI_FILE, r"ipo-docs\..\secret.pdf",
    ]
    assert recent[0].source_url == document_url(CLASS_FILE)
    assert recent[0].source_url.startswith(
        "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal?FileName=ipo-docs%5C"
    )
    assert recent[2].source_url is None
    assert not allowed_file_name("../etc/passwd.pdf")
    with pytest.raises(JournalSourceError, match="listing_layout_changed"):
        parse_listing("<html><body><p>Site under maintenance</p></body></html>")


def test_challenge_detection() -> None:
    assert challenge_reason("text/html", b"<html>Please complete the CAPTCHA</html>")
    assert challenge_reason("text/html", b"<html><title>Request Rejected</title></html>")
    assert challenge_reason("application/pdf", b"%PDF-1.7 captcha") is None
    assert challenge_reason("text/html", _listing([CLASS_FILE]).encode()) is None


class _Source:
    """A deterministic stand-in for the public site; counts every request."""

    def __init__(self, routes: dict[str, list[httpx.Response] | httpx.Response]) -> None:
        self.routes = routes
        self.requests: list[str] = []
        self.sleeps: list[float] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        assert request.method == "GET"
        response = self.routes.get(url)
        if response is None:
            return httpx.Response(404, text="not found")
        if isinstance(response, list):
            item = response.pop(0) if len(response) > 1 else response[0]
        else:
            item = response
        if isinstance(item, Exception):
            raise item
        return item

    def client(self) -> IpIndiaJournalClient:
        return IpIndiaJournalClient(
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
            sleep=self.sleeps.append,
            spacing_seconds=5.0,
            backoff_seconds=30.0,
        )


def _html(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, headers={"content-type": "text/html; charset=utf-8"})


def _pdf_response(data: bytes) -> httpx.Response:
    return httpx.Response(200, content=data, headers={"content-type": "application/pdf"})


def test_client_checks_robots_spaces_requests_and_backs_off() -> None:
    source = _Source(
        {
            ROBOTS_URL: httpx.Response(404),
            LISTING_URL: [_html("busy", 503), _html(_listing([CLASS_FILE]))],
        }
    )
    client = source.client()
    _, listing = client.fetch_listing()
    assert listing.issues == 2
    assert source.requests == [ROBOTS_URL, LISTING_URL, LISTING_URL]
    assert 30.0 in source.sleeps  # backoff after the 503
    assert all(delay <= 5.0 for delay in source.sleeps if delay != 30.0)


def test_client_refuses_robots_disallow_and_challenge_pages() -> None:
    rules = "User-agent: *\nDisallow: /IPOJournal/"
    blocked = _Source({ROBOTS_URL: httpx.Response(200, text=rules)})
    with pytest.raises(JournalSourceRefused, match="robots_disallowed"):
        blocked.client().fetch_listing()
    assert blocked.requests == [ROBOTS_URL]
    moved = _Source({ROBOTS_URL: httpx.Response(302, headers={"location": "/login"})})
    with pytest.raises(JournalSourceRefused, match="robots_unreachable"):
        moved.client().fetch_listing()
    captcha = _Source(
        {ROBOTS_URL: httpx.Response(404), LISTING_URL: _html("<form>Enter the captcha code</form>")}
    )
    with pytest.raises(JournalSourceRefused, match="challenge_detected"):
        captcha.client().fetch_listing()
    assert captcha.requests == [ROBOTS_URL, LISTING_URL]  # no retry around a challenge
    refused = _Source({ROBOTS_URL: httpx.Response(404), LISTING_URL: _html("no", 403)})
    with pytest.raises(JournalSourceRefused, match="access_refused"):
        refused.client().fetch_listing()


def test_client_network_errors_and_non_pdf_documents_fail_cleanly() -> None:
    url = document_url(CLASS_FILE)
    network = _Source({ROBOTS_URL: httpx.Response(404), url: [httpx.ConnectError("down")]})
    with pytest.raises(JournalSourceError, match="network_error"):
        network.client().fetch_document(url)
    assert network.requests.count(url) == 3
    html = _Source({ROBOTS_URL: httpx.Response(404), url: _html("<html>Error</html>")})
    with pytest.raises(JournalSourceError, match="not_a_pdf"):
        html.client().fetch_document(url)
    with pytest.raises(JournalSourceError, match="url_not_allowed"):
        html.client().fetch_document("https://example.com/other.pdf")


# --- end-to-end feed --------------------------------------------------------


def _enable_platform(monkeypatch: pytest.MonkeyPatch, *, feed_on: bool = True) -> None:
    monkeypatch.setenv("CASEOPS_IP_WATCH_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_IP_JOURNAL_FEED_ENABLED", "true" if feed_on else "false")
    get_settings.cache_clear()


def _grant_watch(company_id: str) -> None:
    with get_session_factory()() as session:
        session.add(
            BillingSubscription(
                company_id=company_id,
                status="manual_active",
                segment="law_firm",
                source="iplf052c_test",
                externally_billable=False,
                entitlement_overrides_json={"ip_workspace": True, "ip_watch": True},
            )
        )
        session.commit()


def _second_tenant(client: TestClient) -> tuple[dict, dict]:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Zephyr Marks LLP",
            "company_slug": "zephyr-marks-feed",
            "company_type": "law_firm",
            "owner_full_name": "Zephyr Owner",
            "owner_email": "owner@zephyr-feed.example",
            "owner_password": "ZephyrFounder123!",
        },
    )
    assert response.status_code == 200, response.text
    bootstrap = response.json()
    return bootstrap, auth_headers(str(bootstrap["access_token"]))


def _set_feed(client: TestClient, headers: dict, enabled: bool, version: int | None = None):
    return client.put(
        "/api/ip/watch/journal-feed",
        headers=headers,
        json={"enabled": enabled, "expected_version": version},
    )


def _site(pdf: bytes, *, files: list[str] | None = None) -> _Source:
    files = files or [CLASS_FILE]
    routes: dict = {ROBOTS_URL: httpx.Response(404), LISTING_URL: _html(_listing(files))}
    for name in files:
        routes[document_url(name)] = _pdf_response(pdf)
    return _Source(routes)


def _run(source: _Source, now: datetime = NOW) -> feed.JournalFeedRunResult:
    with get_session_factory()() as session:
        return feed.run_ip_india_journal_feed(session, now=now, client_factory=source.client)


def _count(model, *where) -> int:
    with get_session_factory()() as session:
        return session.scalar(select(func.count()).select_from(model).where(*where)) or 0


def test_kill_switch_and_missing_opt_in_send_no_request(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap, headers, _, _ = _fixture(client, "FEEDOFF")
    _grant_watch(bootstrap["company"]["id"])
    _enable_platform(monkeypatch, feed_on=False)
    source = _site(_pdf(_journal_pages()))
    # The workspace may opt in while the platform switch is off; nothing runs.
    enabled = _set_feed(client, headers, True)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["global_enabled"] is False
    assert _run(source).status == "disabled"
    assert source.requests == []
    _enable_platform(monkeypatch, feed_on=True)
    off = _set_feed(client, headers, False, enabled.json()["setting"]["version"])
    assert off.status_code == 200, off.text
    assert _run(source).status == "no_subscribers"
    assert source.requests == []
    assert _count(IpPublicJournalCheck) == 0


def test_feed_fetches_once_keeps_lineage_and_scopes_hits_to_opted_in_tenants(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "FEEDON")
    company_id = bootstrap["company"]["id"]
    _grant_watch(company_id)
    _enable_platform(monkeypatch)
    profile = _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=bootstrap["membership"]["id"]
    )
    other, other_headers = _second_tenant(client)
    _grant_watch(other["company"]["id"])
    from tests.test_ip_record_workflow import _docket

    other_docket = _docket(client, other_headers, "OTHERFEED")
    other_profile = client.post(
        "/api/ip/watch/profiles",
        headers=other_headers,
        json={
            "docket_id": other_docket["id"],
            "name": "Other tenant ASTER watch",
            "word_terms": ["ASTER"],
            "frequency": "publication",
            "recipient_membership_ids": [other["membership"]["id"]],
        },
    )
    assert other_profile.status_code == 201, other_profile.text
    # Manual intake still works alongside the feed for the opted-out tenant.
    assert _set_feed(client, headers, True).status_code == 200

    pdf = _pdf(_journal_pages())
    source = _site(pdf)
    result = _run(source)
    assert result.status == "ran" and result.check_status == "succeeded"
    assert source.requests == [ROBOTS_URL, LISTING_URL, document_url(CLASS_FILE)]
    assert result.documents_fetched == 1 and result.entries_stored == 4
    assert result.workspace_runs == {"completed": 1}

    with get_session_factory()() as session:
        document = session.scalar(select(IpPublicJournalDocument))
        assert document.status == "parsed"
        assert document.source_url == document_url(CLASS_FILE)
        assert document.retrieved_at is not None
        import hashlib

        assert document.content_sha256 == hashlib.sha256(pdf).hexdigest()
        assert document.journal_number == JOURNAL and document.journal_date == JOURNAL_DATE
        # The shared public store carries no tenant column at all.
        engine = session.get_bind()
        for table in (
            "ip_public_journal_checks",
            "ip_public_journal_documents",
            "ip_public_journal_entries",
        ):
            assert "company_id" not in {col["name"] for col in inspect(engine).get_columns(table)}
        publications = list(
            session.scalars(
                select(IpJournalPublication).where(IpJournalPublication.company_id == company_id)
            )
        )
        # Only entries that match a profile are recorded for the tenant:
        # ASTER RIVAL, ASTER CLOUD (word, class 9) and ZORBIX (class 9 and 42 only).
        assert {item.application_number for item in publications} == {
            "9000001", "9000003", "9000004",
        }
        rival = next(item for item in publications if item.application_number == "9000001")
        assert rival.provider_key == feed.FEED_PROVIDER_KEY
        assert rival.source_url == document_url(CLASS_FILE)
        assert rival.source_page == "PDF page 2, journal page 4284"
        assert rival.source_retrieved_at is not None
        assert rival.raw_evidence_json["document_content_sha256"] == document.content_sha256
        assert rival.raw_evidence_json["journal_page_reference"].endswith("#page=2")
        assert rival.attribution_json["publisher"].startswith("Office of the Controller General")
        hits = list(session.scalars(select(IpWatchHit).where(IpWatchHit.company_id == company_id)))
        assert {hit.profile_id for hit in hits} == {profile["id"]}
        assert {hit.source_url for hit in hits} == {document_url(CLASS_FILE)}
        run = session.scalar(
            select(IpJournalIngestionRun).where(IpJournalIngestionRun.company_id == company_id)
        )
        assert run.provider_key == feed.FEED_PROVIDER_KEY and run.external_call is True
        assert run.cost_minor == 0
        # The opted-out tenant received nothing.
        other_id = other["company"]["id"]
        assert _count(IpJournalPublication, IpJournalPublication.company_id == other_id) == 0
        assert _count(IpWatchHit, IpWatchHit.company_id == other_id) == 0
        assert _count(IpJournalFeedTenantRun, IpJournalFeedTenantRun.company_id == other_id) == 0
    assert client.get("/api/ip/watch", headers=other_headers).json()["hits"] == []
    assert len(client.get("/api/ip/watch", headers=headers).json()["hits"]) == len(hits)

    # Re-running fetches nothing new: the listing is throttled, the document is done.
    again = _site(pdf)
    second = _run(again, NOW + timedelta(minutes=30))
    assert again.requests == []
    assert second.documents_fetched == 0 and second.hits_created == 0
    later = _site(pdf)
    third = _run(later, NOW + timedelta(hours=7))
    assert later.requests == [ROBOTS_URL, LISTING_URL]
    assert third.documents_discovered == 0 and third.documents_fetched == 0
    assert _count(IpPublicJournalEntry) == 4
    assert _count(IpWatchHit, IpWatchHit.company_id == company_id) == len(hits)

    # The second tenant opts in: it is compared with the stored document, no refetch.
    assert _set_feed(client, other_headers, True).status_code == 200
    joined = _site(pdf)
    _run(joined, NOW + timedelta(hours=8))
    assert joined.requests == []
    with get_session_factory()() as session:
        other_pubs = set(
            session.scalars(
                select(IpJournalPublication.application_number).where(
                    IpJournalPublication.company_id == other["company"]["id"]
                )
            )
        )
    assert other_pubs == {"9000001", "9000003"}  # ASTER words only; no class criteria
    status = client.get("/api/ip/watch/journal-feed", headers=headers).json()
    assert status["global_enabled"] is True
    assert status["last_check"]["status"] == "succeeded"
    assert status["documents"][0]["workspace_status"] == "completed"
    assert status["documents"][0]["source_url"] == document_url(CLASS_FILE)


def test_unparsable_documents_are_flagged_for_review_not_dropped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "FEEDREVIEW")
    _grant_watch(bootstrap["company"]["id"])
    _enable_platform(monkeypatch)
    _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=bootstrap["membership"]["id"]
    )
    assert _set_feed(client, headers, True).status_code == 200
    unknown = _pdf([_page(["CORRIGENDA", "A notice the parser does not know"], 1)])
    source = _site(unknown, files=[MULTI_FILE])
    result = _run(source)
    assert result.documents_fetched == 1 and result.review_entries == 1
    status = client.get("/api/ip/watch/journal-feed", headers=headers).json()
    assert status["documents"][0]["status"] == "needs_review"
    assert status["review_total"] == 1
    item = status["review_items"][0]
    assert item["review_reason"] == "no_entries_recognised"
    assert item["source_url"] == document_url(MULTI_FILE) + "#page=1"
    assert _count(IpJournalPublication) == 0


def test_failure_paths_network_layout_and_captcha(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap, headers, _, _ = _fixture(client, "FEEDFAIL")
    _grant_watch(bootstrap["company"]["id"])
    _enable_platform(monkeypatch)
    assert _set_feed(client, headers, True).status_code == 200

    network = _Source({ROBOTS_URL: httpx.Response(404), LISTING_URL: [httpx.ConnectError("down")]})
    result = _run(network)
    assert (result.check_status, result.check_reason) == ("failed", "network_error")
    assert network.requests.count(LISTING_URL) == 3

    layout = _Source({ROBOTS_URL: httpx.Response(404), LISTING_URL: _html("<p>Maintenance</p>")})
    result = _run(layout, NOW + timedelta(hours=7))
    assert (result.check_status, result.check_reason) == ("failed", "listing_layout_changed")

    captcha = _Source(
        {ROBOTS_URL: httpx.Response(404), LISTING_URL: _html("<div class='g-recaptcha'></div>")}
    )
    result = _run(captcha, NOW + timedelta(hours=14))
    assert (result.check_status, result.check_reason) == ("refused", "challenge_detected")
    # After a refusal nothing is sent until the interval passes.
    quiet = _site(_pdf(_journal_pages()))
    result = _run(quiet, NOW + timedelta(hours=15))
    assert quiet.requests == [] and result.check_reason == "recently_refused"
    assert _count(IpPublicJournalDocument) == 0

    # A challenge on a document stops the run and leaves the document pending.
    pdf_url = document_url(CLASS_FILE)
    partial = _Source(
        {
            ROBOTS_URL: httpx.Response(404),
            LISTING_URL: _html(_listing([CLASS_FILE, MULTI_FILE])),
            pdf_url: _html("<p>Are you a robot?</p>"),
            document_url(MULTI_FILE): _pdf_response(_pdf(_journal_pages())),
        }
    )
    result = _run(partial, NOW + timedelta(hours=21))
    assert result.check_status == "refused"
    assert document_url(MULTI_FILE) not in partial.requests
    with get_session_factory()() as session:
        blocked = session.scalar(
            select(IpPublicJournalDocument).where(IpPublicJournalDocument.file_name == CLASS_FILE)
        )
        assert (blocked.status, blocked.attempts, blocked.error_code) == (
            "pending", 1, "challenge_detected",
        )
    checks = _count(IpPublicJournalCheck, IpPublicJournalCheck.status == "refused")
    assert checks == 2


def test_setting_requires_watch_operations_and_versions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap, headers, _, _ = _fixture(client, "FEEDGATE")
    monkeypatch.setenv("CASEOPS_IP_WATCH_ENABLED", "true")
    get_settings.cache_clear()
    refused = _set_feed(client, headers, True)
    assert refused.status_code == 403, refused.text
    assert refused.json()["feature_id"] == "watch_operations"
    _grant_watch(bootstrap["company"]["id"])
    first = _set_feed(client, headers, True)
    assert first.status_code == 200, first.text
    setting = first.json()["setting"]
    assert setting["run_as_membership_id"] == bootstrap["membership"]["id"]
    stale = _set_feed(client, headers, False, setting["version"] + 5)
    assert stale.status_code == 409
    fresh = _set_feed(client, headers, False, setting["version"])
    assert fresh.status_code == 200 and fresh.json()["setting"]["enabled"] is False
    with get_session_factory()() as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.company_id == bootstrap["company"]["id"],
                    AuditEvent.action.like("ip_watch.journal_feed_%"),
                )
            )
        )
    assert actions == {"ip_watch.journal_feed_enabled", "ip_watch.journal_feed_disabled"}
    # With the automated feature off, a workspace can still turn the feed off
    # but cannot turn it on.
    on = _set_feed(client, headers, True, fresh.json()["setting"]["version"])
    assert on.status_code == 200, on.text
    monkeypatch.setenv("CASEOPS_IP_WATCH_ENABLED", "false")
    get_settings.cache_clear()
    off = _set_feed(client, headers, False, on.json()["setting"]["version"])
    assert off.status_code == 200, off.text
    again = _set_feed(client, headers, True, off.json()["setting"]["version"])
    assert again.status_code == 503, again.text


def test_workspace_runs_fail_closed_for_broad_profiles_and_inactive_actor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap, headers, docket, _ = _fixture(client, "FEEDLIMIT")
    company_id = bootstrap["company"]["id"]
    _grant_watch(company_id)
    _enable_platform(monkeypatch)
    _profile(
        client, headers=headers, docket_id=docket["id"], recipient_id=bootstrap["membership"]["id"]
    )
    assert _set_feed(client, headers, True).status_code == 200
    monkeypatch.setattr(feed, "MAX_MATCHES_PER_DOCUMENT", 2)
    result = _run(_site(_pdf(_journal_pages())))
    assert result.workspace_runs == {"match_limit_exceeded": 1}
    assert _count(IpJournalPublication, IpJournalPublication.company_id == company_id) == 0
    # Terminal and visible: a later run neither retries it nor calls the source.
    quiet = _site(b"")
    assert _run(quiet, NOW + timedelta(minutes=5)).workspace_runs == {}
    assert quiet.requests == []

    with get_session_factory()() as session:
        session.query(IpJournalFeedTenantRun).delete()
        setting = session.get(IpJournalFeedSetting, company_id)
        membership = session.get(CompanyMembership, setting.run_as_membership_id)
        membership.is_active = False
        session.commit()
    monkeypatch.setattr(feed, "MAX_MATCHES_PER_DOCUMENT", 500)
    result = _run(_site(b""), NOW + timedelta(minutes=10))
    assert result.workspace_runs == {"actor_unavailable": 1}
    assert _count(IpWatchHit, IpWatchHit.company_id == company_id) == 0
