"""Real HTTP acceptance inside an isolated, exact-image Docker API."""

import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx


STATE = Path(os.environ.get('CASEOPS_COLD_STATE', '/tmp/caseops-cold-http-state.json'))
BASE = 'http://127.0.0.1:8000'
HEADERS = {'X-CaseOps-Automated-Test': 'no-paid-providers'}
CLEAN = b'Harmless local upload acceptance text.'
EICAR = b'X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
PORTFOLIO_PATH = '/api/ip/portfolio?limit=100'
PORTFOLIO_TITLE = 'Cold startup portfolio fixture'


def seed():
    """Prepare canonical synthetic records before the timed serving process exists."""
    from fastapi.testclient import TestClient

    from caseops_api.main import app

    # No lifespan, model warm-up or uploads in this preparation-only process.
    client = TestClient(app, headers=HEADERS)
    account = expect(client.post('/api/bootstrap/company', json={
        'company_name': 'Cold HTTP Acceptance', 'company_slug': 'test-cold-http',
        'company_type': 'law_firm', 'owner_full_name': 'Local Acceptance',
        'owner_email': 'cold@testfirm.com', 'owner_password': 'LocalColdOnly123!',
    }), 200)
    token = account['access_token']
    client.headers['Authorization'] = f'Bearer {token}'
    matter = expect(client.post('/api/matters/', json={
        'title': 'Cold scanner upload acceptance', 'matter_code': 'COLD-HTTP-001',
        'practice_area': 'Litigation', 'forum_level': 'high_court', 'status': 'intake',
    }), 200)
    docket = expect(client.post('/api/ip/dockets', json={
        'title': PORTFOLIO_TITLE, 'matter_id': matter['id'], 'restricted': False,
        'particulars': {
            'form_key': 'TM-A', 'form_version': '2026.1', 'mark_kind': 'word',
            'representation': {'text': 'COLD', 'evidence_reference': 'fixture:cold'},
            'classes': [{'class_number': 9, 'specification': 'Downloadable software'}],
            'use_priority': None, 'parties': [{'role': 'applicant', 'name': 'Fixture LLP'}],
            'agent': None, 'filing_manifest': [{
                'key': 'representation', 'label': 'Mark representation', 'required': True,
                'evidence_reference': 'fixture:cold',
            }],
        },
    }), 201)
    asset = expect(client.post(f"/api/ip/dockets/{docket['id']}/assets", json={
        'asset_kind': 'trademark', 'jurisdiction': 'IN', 'title': PORTFOLIO_TITLE,
    }), 201)
    application = expect(client.post(f"/api/ip/dockets/{docket['id']}/applications", json={
        'asset_id': asset['id'], 'office': 'IP India', 'jurisdiction': 'IN',
        'filing_phase': 'draft',
    }), 201)['application']
    STATE.write_text(json.dumps({
        'token': token, 'matter_id': matter['id'], 'attachments': [],
        'application_id': application['id'], 'asset_id': asset['id'], 'docket_id': docket['id'],
    }))
    client.close()
    print(json.dumps({'seeded': True, 'portfolio_records': 1, 'uploads': 0}))


def portfolio(client, state, *, timeout=5):
    started = time.monotonic()
    body = expect(client.get(PORTFOLIO_PATH, timeout=timeout), 200)
    duration = time.monotonic() - started
    assert body['counts']['total'] == 1, body
    assert len(body['rows']) == 1, body
    row = body['rows'][0]
    assert row['application_id'] == state['application_id'], row
    assert row['asset_id'] == state['asset_id'], row
    assert row['asset_title'] == PORTFOLIO_TITLE, row
    assert row['jurisdiction'] == 'IN', row
    assert row['filing_phase'] == 'draft', row
    return {'path': PORTFOLIO_PATH, 'http_status': 200, 'seconds': duration,
            'exact_record_verified': True, 'records': 1}


def wait_portfolio(client, state, started_epoch):
    deadline = time.monotonic() + max(0, 30 - (time.time() - started_epoch))
    attempts = 0
    result = None
    while time.monotonic() < deadline:
        attempts += 1
        try:
            result = portfolio(client, state, timeout=min(5, deadline - time.monotonic()))
            break
        except (httpx.ConnectError, httpx.ConnectTimeout):
            # Only a pre-serving connection is retried, never a failed HTTP response.
            time.sleep(0.05)
    elapsed = time.time() - started_epoch
    print(json.dumps({'cold_http_seconds': elapsed, 'attempts': attempts,
                      'cold_gate_passed': result is not None and elapsed <= 30,
                      'portfolio': result}))


def expect(response, status):
    assert response.status_code == status, (response.status_code, response.text[:1000])
    return response.json()


def attachment_ids(client, matter_id):
    data = expect(client.get(f'/api/matters/{matter_id}/workspace'), 200)
    return sorted(row['id'] for row in data['attachments'])


def upload(client, matter_id, name, content):
    return client.post(f'/api/matters/{matter_id}/attachments', files={'file': (name, content, 'text/plain')})


def assert_download(client, matter_id, attachment_id, content):
    response = client.get(f'/api/matters/{matter_id}/attachments/{attachment_id}/download')
    assert response.status_code == 200, (response.status_code, response.text[:1000])
    assert response.content == content


def main(mode):
    if mode == 'seed':
        seed()
        return
    with httpx.Client(base_url=BASE, headers=HEADERS, timeout=20) as client:
        state = json.loads(STATE.read_text())
        client.headers['Authorization'] = f"Bearer {state['token']}"
        matter_id = state['matter_id']
        if mode == 'wait-portfolio':
            wait_portfolio(client, state, float(sys.argv[2]))
            return
        if mode == 'portfolio':
            print(json.dumps(portfolio(client, state)))
            return
        if mode == 'healthy':
            clean = expect(upload(client, matter_id, 'clean.txt', CLEAN), 200)
            assert_download(client, matter_id, clean['id'], CLEAN)
            before = attachment_ids(client, matter_id)
            assert before == [clean['id']]
            rejected = expect(upload(client, matter_id, 'eicar.txt', EICAR), 400)
            assert 'virus signature' in json.dumps(rejected).lower(), rejected
            assert attachment_ids(client, matter_id) == before
            state['attachments'] = before
            STATE.write_text(json.dumps(state))
            print(json.dumps({'clean_upload_http': 200, 'byte_identical_download': True,
                              'eicar_upload_http': 400, 'no_rejected_attachment': True,
                              'clean_sha256': hashlib.sha256(CLEAN).hexdigest()}))
            return
        if mode == 'unavailable':
            rejected = expect(upload(client, matter_id, 'outage.txt', CLEAN), 503)
            assert 'scanner is unavailable' in json.dumps(rejected).lower(), rejected
            assert attachment_ids(client, matter_id) == state['attachments']
            started = time.monotonic()
            assert expect(client.get('/api/health'), 200)['status'] == 'ok'
            health_seconds = time.monotonic() - started
            assert health_seconds < 5
            print(json.dumps({'scanner_outage_upload_http': 503, 'no_rejected_attachment': True,
                              'health_seconds': health_seconds}))
        elif mode == 'recovered':
            recovered = expect(upload(client, matter_id, 'recovered.txt', CLEAN + b' Recovered.'), 200)
            assert_download(client, matter_id, recovered['id'], CLEAN + b' Recovered.')
            assert attachment_ids(client, matter_id) == sorted(state['attachments'] + [recovered['id']])
            print(json.dumps({'recovered_upload_http': 200, 'byte_identical_download': True,
                              'persisted_attachment_count': 2}))
        else:
            raise ValueError('Unknown acceptance mode')


if __name__ == '__main__':
    main(sys.argv[1])
