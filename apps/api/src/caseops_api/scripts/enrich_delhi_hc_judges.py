"""Enrich Delhi HC judges JSON with per-judge profile-page bio + url.

For each name in ``seed_data/delhi-hc_sitting_judges.json``, fetch the
official profile page at
``https://delhihighcourt.nic.in/web/Judges/<slug>``, extract the bio
prose, and write it back to the JSON file (keys: ``profile_url``,
``bio_text``, ``slug``).

Why bio text instead of parsed dates: Delhi HC profile pages render
biographical info as natural-language prose ("She enrolled with the
Bar in 1991") rather than the structured form sci.gov.in uses. A
regex parser would catch ~30% of fields with ~50% accuracy. Storing
the bio verbatim + clicking through to the source is more honest
than fabricated dates.

Run: ``python -m caseops_api.scripts.enrich_delhi_hc_judges``

Idempotent — re-running re-fetches each profile and overwrites
profile_url + bio_text but preserves the original ``name``. 1-second
politeness delay.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

JSON_PATH = (
    Path(__file__).resolve().parent
    / "seed_data" / "delhi-hc_sitting_judges.json"
)
SITTING_JUDGES_URL = "https://delhihighcourt.nic.in/web/CJ_Sitting_Judges"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)
SLEEP_SEC = 1.0


def _fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — network/format errors all opaque
        print(f"  [warn] {url} -> {type(exc).__name__}: {exc}", file=sys.stderr)
        return None


def _slug_from_anchor(href: str) -> str | None:
    """``/web/Judges/justice-prathiba-m-singh`` -> ``justice-prathiba-m-singh``."""
    m = re.match(r"^/web/Judges/(.+)$", href.strip())
    return m.group(1) if m else None


def collect_profile_urls() -> dict[str, str]:
    """Walk the paginated sitting-judges page; build a map from
    name (stripped of honorific, lowercased) to the per-judge profile
    URL slug."""
    out: dict[str, str] = {}
    for page in range(1, 6):
        url = SITTING_JUDGES_URL if page == 1 else f"{SITTING_JUDGES_URL}?page={page}"
        body = _fetch(url)
        if body is None:
            break
        anchors = re.findall(
            r'<a[^>]+href="([^"]+)"[^>]*>([^<]+)</a>',
            body, re.IGNORECASE,
        )
        added = 0
        for href, text in anchors:
            slug = _slug_from_anchor(href)
            if not slug:
                continue
            normalised = re.sub(r"\s+", " ", text).strip()
            normalised = (
                normalised.replace("&#039;", "'").replace("&amp;", "&")
            )
            # Strip honorific to align with the seed JSON's keys.
            stripped = re.sub(
                r"^(?:Hon[\u2019']?ble\s+)?(?:Mr\.?\s+|Ms\.?\s+|Mrs\.?\s+)?"
                r"(?:Chief\s+Justice|Justice)\s+",
                "", normalised, flags=re.IGNORECASE,
            ).strip()
            key = stripped.lower()
            if key and key not in out:
                out[key] = slug
                added += 1
        print(f"  page {page}: +{added} judge URLs")
        if added == 0 and page > 1:
            break
        time.sleep(SLEEP_SEC)
    return out


def extract_bio(html: str) -> str | None:
    clean = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    clean = re.sub(r"<style[\s\S]*?</style>", "", clean, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", clean)
    text = re.sub(r"\s+", " ", text)
    text = (
        text.replace("\u00a0", " ")
        .replace("&#039;", "'")
        .replace("&amp;", "&")
        .replace("&nbsp;", " ")
    )
    # Bio block on the page is repeated as `Back Justice X Justice X
    # <bio>`. Capture from the duplicate marker to the next major
    # navigation block.
    m = re.search(
        r"Back\s+(Justice\s[\w.\s\-]+?)\s+\1\s+(.+?)"
        r"(?:Notifications\s*&|Citizen Charter|©|All Rights Reserved|Copyright)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if m is None:
        # Fallback to the chief-justice variant.
        m = re.search(
            r"Back\s+(Chief\s+Justice\s[\w.\s\-]+?)\s+\1\s+(.+?)"
            r"(?:Notifications\s*&|Citizen Charter|©|All Rights Reserved|Copyright)",
            text, re.IGNORECASE | re.DOTALL,
        )
    if m is None:
        return None
    bio = m.group(2).strip()
    # Cap the bio length (raw page bios run 200-2000 chars; cap at
    # 2000 so the JSON file stays sane).
    return bio[:2000]


def main() -> int:
    if not JSON_PATH.exists():
        print(f"ABORT: {JSON_PATH} missing", file=sys.stderr)
        return 1
    seeds = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    print(f"loaded {len(seeds)} Delhi HC judges from {JSON_PATH.name}")

    print("=== step 1: collect profile URLs ===")
    slug_by_name = collect_profile_urls()
    print(f"  collected {len(slug_by_name)} URLs")

    print("=== step 2: fetch each profile + extract bio ===")
    enriched = 0
    failed = 0
    for i, entry in enumerate(seeds, start=1):
        raw_name = entry.get("name") or ""
        # The seed JSON stores names as 'Justice Foo Bar'; strip
        # 'Justice ' prefix to match slug map.
        stripped = re.sub(
            r"^Justice\s+", "", raw_name, flags=re.IGNORECASE,
        ).strip().lower()
        slug = slug_by_name.get(stripped)
        if not slug:
            print(f"  [{i}/{len(seeds)}] {raw_name!r} -> no slug match")
            failed += 1
            continue
        profile_url = f"https://delhihighcourt.nic.in/web/Judges/{slug}"
        body = _fetch(profile_url)
        if body is None:
            failed += 1
            continue
        bio = extract_bio(body)
        entry["slug"] = slug
        entry["profile_url"] = profile_url
        entry["bio_text"] = bio
        if bio:
            enriched += 1
            print(f"  [{i}/{len(seeds)}] {raw_name!r} -> bio {len(bio)} chars")
        else:
            print(f"  [{i}/{len(seeds)}] {raw_name!r} -> no bio extracted")
        time.sleep(SLEEP_SEC)

    JSON_PATH.write_text(
        json.dumps(seeds, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    print()
    print(f"DONE: enriched={enriched}/{len(seeds)} failed={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
