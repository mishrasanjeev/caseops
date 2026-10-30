"""Additive real-API fixture preparation for the dated 23-case native gate."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sys

ROOT = Path(os.environ.get("CASEOPS_MOBILE_STATE", "/fixture-state"))
fixture = None
SEARCH_KINDS = ("matter_code", "case_number", "filing_number", "cnr_number", "temporary_e_case_number")
JOIN = " \u00b7 "


def _load_local_transport():
    import hashlib as _hashlib
    import os as _os
    import stat as _stat
    _path = Path(__file__).absolute().with_name("local-transport.py")
    _keys = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    _frame = lambda value: tuple(getattr(value, key) for key in _keys)
    assert _path.resolve(strict=True) == _path, "Canonical local transport source required"
    def _namespace():
        rows = []
        for parent in _path.parents:
            value = parent.lstat()
            assert len(rows) < 128 and _stat.S_ISDIR(value.st_mode) and not _stat.S_ISLNK(value.st_mode), "Local transport source namespace required"
            rows.append((str(parent), *(getattr(value, key) for key in _keys[:5])))
        return rows
    _parents = _namespace()
    _named = _path.lstat()
    _fd = _os.open(_path, _os.O_RDONLY | getattr(_os, "O_NOFOLLOW", 0) | getattr(_os, "O_NONBLOCK", 0) | getattr(_os, "O_BINARY", 0))
    try:
        _first = _os.fstat(_fd)
        assert _stat.S_ISREG(_first.st_mode) and not _stat.S_ISLNK(_named.st_mode) and _first.st_nlink == 1 and _first.st_uid == Path(__file__).lstat().st_uid, "Local transport source identity required"
        assert 0 < _first.st_size <= 16384 and all(getattr(_first, key) == getattr(_named, key) for key in _keys if not (_os.name == "nt" and key == "st_dev" and _named.st_dev == 0)), "Local transport named descriptor mismatch"
        _data = bytearray()
        while len(_data) <= _first.st_size:
            _part = _os.read(_fd, min(65536, _first.st_size + 1 - len(_data)))
            if not _part:
                break
            _data.extend(_part)
        _raw = bytes(_data)
        assert len(_raw) == _first.st_size and _hashlib.sha256(_raw).hexdigest() == "95180cd961891d9056d2a4d491e9239c6f49d4de2562c35e6d48610d767dd6ae" and _frame(_first) == _frame(_os.fstat(_fd)) and _frame(_named) == _frame(_path.lstat()) and _parents == _namespace(), "Local transport source changed"
    finally:
        _os.close(_fd)
    _scope = {"__name__": "caseops_local_transport", "__file__": str(_path)}
    exec(compile(_raw, str(_path), "exec"), _scope)
    return _scope

_LOCAL_TRANSPORT = _load_local_transport()

def extension_auth(inputs, config):
    assert isinstance(inputs, dict) and isinstance(config, dict), "Extension input and config objects required"
    expected = _LOCAL_TRANSPORT['witness'](config, inputs, require_api=False)
    platform, origin = expected['platform'], expected['webOrigin']
    auth = {"webOrigin": origin, "companySlug": "test-legal",
            "mode": "web-context" if platform == "ios" else "native-firefox",
            "emailEnv": "CASEOPS_MOBILE_CORE_EMAIL", "passwordEnv": "CASEOPS_MOBILE_CORE_PASSWORD",
            "mfaRequired": True, "totpSecretEnv": "CASEOPS_MOBILE_CORE_TOTP_SECRET"}
    if platform == "ios":
        auth["iosConsent"] = True
    return auth


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    fixture.save(name, value)


def matter_ref(row, search=None):
    result = {"id": row["id"], "title": row["title"], "identityLabel": row["matter_code"]}
    if search:
        assert search not in (result["title"], result["identityLabel"])
        result["search"] = search
    return result


def main():
    global fixture
    name = sys.argv[1]
    assert re.fullmatch(r"extend-input-[a-f0-9]{12}\.json", name)
    inputs = json.loads((ROOT / name).read_text(encoding="utf-8"))
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    auth = extension_auth(inputs, config)
    nonce = inputs["iteration"]
    assert re.fullmatch(r"[a-f0-9]{12}", nonce)
    spec = importlib.util.spec_from_file_location("local_fixture", Path(__file__).with_name("local-fixture.py"))
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    base_path = ROOT / "seed.json"
    base_hash = sha(base_path)
    base = json.loads(base_path.read_text(encoding="utf-8"))
    owner_credentials = json.loads((ROOT / "credentials.json").read_text(encoding="utf-8"))
    stage = {"iteration": nonce, "baseSeedSha256": base_hash, "inputSha256": sha(ROOT / name), "stages": []}
    journal = (ROOT / f"extend-progress-{nonce}.jsonl").open("x", encoding="utf-8")

    def checkpoint(label, values):
        stage["stages"].append(label)
        journal.write(json.dumps({"stage": label, **values}) + "\n")
        journal.flush()
        os.fsync(journal.fileno())

    with fixture.client() as owner, fixture.client() as member, fixture.client() as foreign:
        identity = fixture.login(owner, owner_credentials)
        assert identity["company"]["id"] == base["companyId"] and identity["membership"]["role"] == "owner"
        mid = base["matter"]["id"]
        original = fixture.expect(owner.get(f"/api/matters/{mid}"))
        save(f"extend-original-primary-{nonce}.json", original)
        assert original["status"] in ("intake", "active", "on_hold") and original["is_active"]
        patch = {"expected_updated_at": original["updated_at"]}
        candidates = {"case_number": f"CASE-LOCAL-{nonce.upper()}",
                      "filing_number": f"FILING-LOCAL-{nonce.upper()}",
                      "cnr_number": "MOBL" + nonce.upper(),
                      "temporary_e_case_number": f"TEMP-LOCAL-{nonce.upper()}"}
        for key, value in candidates.items():
            if not original.get(key):
                patch[key] = value
        if not original.get("next_hearing_on"):
            patch["next_hearing_on"] = base["calendarDate"]
        if len(patch) > 1:
            fixture.expect(owner.patch(f"/api/matters/{mid}", json=patch))
        primary = fixture.expect(owner.get(f"/api/matters/{mid}"))
        for key in SEARCH_KINDS:
            assert primary[key] == (patch[key] if key in patch else original[key]), "Identifier persistence mismatch"
        assert len({primary[key] for key in SEARCH_KINDS}) == 5
        assert primary["matter_code"] == original["matter_code"] and primary["title"] == original["title"]
        checkpoint("supported-api-identifiers-reread", {"matterId": mid, "changedFields": sorted(set(patch) - {"expected_updated_at"})})

        credentials = {"email": f"mobile-core-{nonce}@example.com", "password": "Aa1!" + secrets.token_urlsafe(24),
                       "company_slug": "test-legal", "full_name": f"Mobile Core Member {nonce}"}
        credentials_name = f"core-credentials-{nonce}.json"
        save(credentials_name, credentials)
        user = fixture.expect(owner.post("/api/companies/current/users", json={
            "full_name": credentials["full_name"], "email": credentials["email"],
            "password": credentials["password"], "role": "member",
        }))
        member_identity = fixture.login(member, credentials)
        assert member_identity["membership"]["id"] == user["membership_id"]
        assert member_identity["membership"]["role"] == "member", "Owner bypass cannot prove Matter access revocation"
        checkpoint("dedicated-member-created", {"membershipId": user["membership_id"], "userId": user["user_id"]})
        # Actual enrollment, not a prepared browser session or native token family.
        from caseops_api.services.security import TOTP_PERIOD_SECONDS, _hotp
        import time
        enrollment = fixture.expect(member.post("/api/auth/mfa/enroll"))
        secret = enrollment["secret"]
        fixture.expect(member.post("/api/auth/mfa/enroll/verify", json={
            "code": _hotp(secret, int(time.time()) // TOTP_PERIOD_SECONDS),
        }))
        credentials["totp_secret"] = secret
        # The original credentials and initial seed are never changed.
        fixture.update_private(credentials_name, credentials)
        task = fixture.expect(owner.post(f"/api/matters/{mid}/tasks", json={
            "title": f"Inspect native core synthetic file {nonce}", "due_on": base["calendarDate"],
            "owner_membership_id": user["membership_id"], "priority": "high",
        }))

        targets = {}
        for kind in ("lifecycle", "access"):
            search = f"LOOKUP-{kind.upper()}-{nonce.upper()}"
            target = fixture.expect(owner.post("/api/matters/", json={
                "title": f"Synthetic {kind} boundary {nonce}", "matter_code": f"CORE-{kind.upper()}-{nonce.upper()}",
                "case_number": search, "practice_area": "Litigation", "forum_level": "advisory", "status": "intake",
            }))
            assert target["is_active"] and target["status"] == "intake" and target["lifecycle_version"] == 0
            targets[kind] = matter_ref(target, search)
            checkpoint(f"fresh-{kind}-target-created", {"matterId": target["id"], "lifecycleVersion": 0})
        access_id = targets["access"]["id"]
        fixture.expect(owner.post(f"/api/matters/{access_id}/access/restricted", json={"restricted": True}))
        grant = fixture.expect(owner.post(f"/api/matters/{access_id}/access/grants", json={
            "membership_id": user["membership_id"], "reason": "Dedicated native stale-access fixture grant",
        }))
        for target in targets.values():
            persisted = fixture.expect(member.get(f"/api/matters/{target['id']}/workspace"))
            assert persisted["matter"]["id"] == target["id"] and not persisted["notes"]
        checkpoint("fresh-targets-readable-not-mutated", {"accessGrantId": grant["id"], "destructiveControlsExecuted": False})

        other = fixture.login(foreign, {**owner_credentials, "email": "mobile-other@example.com", "company_slug": "test-mobile-other"})
        assert other["company"]["id"] == base["otherCompanyId"]
        foreign_id = base["otherMatterId"]
        foreign_before = fixture.expect(foreign.get(f"/api/matters/{foreign_id}"))
        foreign_search = foreign_before.get("case_number") or f"FOREIGN-LOOKUP-{nonce.upper()}"
        if not foreign_before.get("case_number"):
            fixture.expect(foreign.patch(f"/api/matters/{foreign_id}", json={
                "expected_updated_at": foreign_before["updated_at"], "case_number": foreign_search,
            }))
        foreign_row = fixture.expect(foreign.get(f"/api/matters/{foreign_id}"))
        assert foreign_row["case_number"] == foreign_search
        negative = fixture.expect(member.get("/api/matters/", params={"q": foreign_search, "limit": 25}))
        assert negative["matters"] == []
        fixture.expect(member.get(f"/api/matters/{foreign_id}/workspace"), 404)

        primary_ref = matter_ref(primary)
        searches = []
        for kind in SEARCH_KINDS:
            value = primary[kind]
            rows = fixture.expect(member.get("/api/matters/", params={"q": value, "limit": 25}))["matters"]
            assert [row["id"] for row in rows] == [mid], f"Exact {kind} search did not return the admitted Matter"
            searches.append({"kind": kind, "value": value})
        workspace = fixture.expect(member.get(f"/api/matters/{mid}/workspace"))
        for kind in SEARCH_KINDS:
            assert workspace["matter"][kind] == primary[kind]
        today = fixture.expect(member.get("/api/me/today", params={"horizon_days": 7}))
        today_task = fixture.one_or_none(today["tasks_due_or_overdue"], "id", task["id"])
        assert today_task and today_task["matter"]["id"] == mid
        draft = fixture.expect(member.get(f"/api/matters/{mid}/drafts/{base['draftId']}"))
        current = fixture.one_or_none(draft["versions"], "id", draft["current_version_id"])
        assert current and current["verified_citation_count"] == 0 and json.loads(json.dumps(current["citations"])) == []
        agenda = fixture.expect(member.get("/api/calendar/events", params={"from": base["calendarDate"], "to": base["calendarDate"]}))
        event = fixture.one_or_none(agenda["events"], "id", "hearing:" + base["hearingId"])
        assert event and event["matter_id"] == mid and event["occurs_on"] == base["calendarDate"]
        day_label = inputs["dateLabels"][base["calendarDate"]]
        task_meta = JOIN.join(("task", day_label, today_task["status"], today_task["priority"]))
        task_expectation = {"id": task["id"], "kind": "task", "title": task["title"],
                            "metaLabel": task_meta, "matter": primary_ref}
        calendar_meta = JOIN.join(str(value) for value in (
            day_label, event["display_type"].replace("_", " "),
            f"{event['hearing_time']} {event['timezone']}", event.get("detail"),
        ) if value)
        receipt = {
            "environment": "docker-integration", "syntheticDataOnly": True,
            "coreInventory": "native-core-2026-10-25", "iteration": nonce,
            "platform": config.get("CASEOPS_MOBILE_PLATFORM", "android"),
            **_LOCAL_TRANSPORT["fields"](config),
            "baseSeed": {"file": "seed.json", "sha256": base_hash},
            "servingBuild": fixture.expect(owner.get("/api/build")),
            "principalLabel": credentials["full_name"], "workspaceLabel": identity["company"]["name"],
            "companyId": base["companyId"], "membershipId": user["membership_id"], "userId": user["user_id"],
            "ownerMembershipId": identity["membership"]["id"], "credentialsFile": credentials_name,
            "auth": auth,
            "matter": {**primary_ref, "search": primary["matter_code"], "searches": searches},
            "today": {**task_expectation, "dueOn": today_task["due_on"], "dateLabel": day_label, "status": today_task["status"]},
            "work": {"task": task_expectation, "draft": {
                "id": draft["id"], "kind": "draft", "title": draft["title"], "matter": primary_ref,
                "entry": "matter-work", "statusLabel": JOIN.join((draft["status"], "Read-only")),
                "revisionLabel": f"Revision {current['revision']}" + JOIN + current["id"],
                "body": current["body"], "citations": current["citations"],
                "verifiedCitationCountLabel": f"{current['verified_citation_count']} server-marked verified citations. This is not certification of legal accuracy.",
            }},
            "calendar": {"eventId": event["id"], "day": base["calendarDate"], "dayLabel": day_label, "title": event["title"],
                         "metaLabel": calendar_meta, "matter": primary_ref,
                         "nextHearingLabel": inputs["dateLabels"][primary["next_hearing_on"]]},
            "foreignMatter": matter_ref(foreign_row, foreign_search),
            "lifecycleMatter": targets["lifecycle"], "accessMatter": targets["access"],
            "accessGrantId": grant["id"], "noteRoute": f"/api/matters/{mid}/notes",
            "matterReloadRoute": f"/api/matters/{mid}/workspace",
            "source": {"matterId": mid, "id": base["sourceId"], "sha256": base["sourceSha256"]},
            "localeEvidence": inputs["localeEvidence"], "locale": inputs["locale"],
            "renderedLabelsAreExpectationsNotNativeProof": True,
            "originalPrimaryRecord": original, "persistedPrimaryRecord": primary,
            "originalForeignRecord": foreign_before, "persistedForeignRecord": foreign_row,
            "nativeBrowserCookiesOrTokensPrepared": False, "destructiveControlsExecuted": False,
        }
        assert sha(base_path) == base_hash, "Original seed was changed"
        receipt_name = f"extended-seed-{nonce}.json"
        save(receipt_name, receipt)
        checkpoint("extended-seed-complete", {"receipt": receipt_name, "sha256": sha(ROOT / receipt_name)})
        journal.close()
        print(json.dumps({"extendedSeed": receipt_name, "sha256": sha(ROOT / receipt_name),
                          "credentialsFile": credentials_name, "freshTargets": True, "destructiveControlsExecuted": False}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback
        print(json.dumps({"failed": "extend", "errorType": type(error).__name__,
                          "frames": [{"file": Path(frame.filename).name, "line": frame.lineno} for frame in traceback.extract_tb(error.__traceback__)],
                          "detail": str(error) if isinstance(error, AssertionError) else "Sanitized fixture setup failure"}), file=sys.stderr)
        sys.exit(1)
