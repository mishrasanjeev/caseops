import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./env";
import { expectStatus } from "./iplf058b";

export const INTELLIGENT_REVIEW_PASSWORD = "ReviewWorkflow2026!";

function grantIpEntitlement(companyId: string): void {
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() ||
    (process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python"));
  const script = [
    "import os",
    "from caseops_api.db.models import BillingSubscription",
    "from caseops_api.db.session import get_session_factory",
    "session=get_session_factory()()",
    "session.add(BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf_063b_playwright',externally_billable=False,entitlement_overrides_json={'ip_workspace': True}))",
    "session.commit()",
    "session.close()",
  ].join("; ");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      CASEOPS_E2E_COMPANY_ID: companyId,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

export async function bootstrapIntelligentReviewTenant(api: APIRequestContext) {
  const slug = `intelligent-review-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 063B Intelligent Review LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Intelligent Review Partner",
      owner_email: email,
      owner_password: INTELLIGENT_REVIEW_PASSWORD,
    },
  });
  await expectStatus(response, 200, "bootstrap intelligent-review tenant");
  const tenant = await response.json();
  grantIpEntitlement(tenant.company.id);
  return { ...tenant, slug, email };
}

export async function enableIntelligentReviewIpWorkspace(
  api: APIRequestContext,
  tenant: { access_token: string; membership: { id: string } },
) {
  const headers = { Authorization: `Bearer ${tenant.access_token}` };
  const configured = await api.put(`${apiBaseUrl}/api/ip/workspace/configuration`, {
    headers,
    data: {
      expected_version: null,
      enabled_asset_types: ["trademark"],
      jurisdictions: ["IN"],
      offices: ["Trade Marks Registry Delhi"],
      timezone: "Asia/Kolkata",
      holiday_calendar_key: "iplf-063b-calendar",
      working_day_policy: { working_weekdays: [0, 1, 2, 3, 4] },
      document_taxonomy_version: "ip-taxonomy-2026.1",
      event_catalog_version: "ip-events-v1",
      deadline_rule_versions: { IN: "2026.1" },
      notification_channels: ["in_app"],
      critical_event_policy: { escalation_after_minutes: 30 },
      escalation_owner_membership_id: tenant.membership.id,
      provider_keys: [],
      provider_terms_version: null,
      accept_provider_terms: false,
    },
  });
  await expectStatus(configured, 200, "configure intelligent-review IP workspace");
  const enabled = await api.post(`${apiBaseUrl}/api/ip/workspace/enable`, {
    headers,
    data: {
      expected_config_version: (await configured.json()).configuration.version,
      enabled_automations: [],
    },
  });
  await expectStatus(enabled, 200, "enable intelligent-review IP workspace");
  return headers;
}

export async function signInIntelligentReviewTenant(
  page: Page,
  tenant: { slug: string; email: string },
) {
  const response = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: tenant.slug,
      email: tenant.email,
      password: INTELLIGENT_REVIEW_PASSWORD,
    },
  });
  await expectStatus(response, 200, "intelligent-review sign-in");
  const session = await response.json();
  await page.goto("/");
  await page.evaluate(
    (context) => {
      window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
    },
    {
      company: session.company,
      user: session.user,
      membership: session.membership,
      capabilities: session.capabilities,
    },
  );
  return session;
}

export function createIntelligentReviewAuthorityFixture(): {
  accessibleIds: string[];
  inaccessibleId: string;
  sourceUrls: string[];
} {
  const python =
    process.env.CASEOPS_E2E_PYTHON?.trim() ||
    (process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python"));
  const script = String.raw`
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from caseops_api.db.models import AuthorityDocument
from caseops_api.db.session import get_session_factory

s = get_session_factory()()
run = uuid4().hex[:10]
passages = [
    'Prior continuous use supported the passing off claim on the proved record.',
    'A visual comparison alone was insufficient without evidence of likely confusion.',
]
ids = []
urls = []
for index, passage in enumerate(passages):
    url = 'https://www.sci.gov.in/'
    document = AuthorityDocument(
        source='supreme_court_latest_orders',
        adapter_name='iplf-063b-playwright-v1',
        court_name='Supreme Court of India' if index == 0 else 'Delhi High Court',
        forum_level='supreme_court' if index == 0 else 'high_court',
        document_type='judgment',
        title=f'IPLF 063B review authority {index + 1} {run}',
        case_reference=f'IPLF 063B {index + 1}/2026',
        neutral_citation=f'2026:IR:{run}:{index + 1}',
        decision_date=date(2026, 8, 20 + index),
        canonical_key=f'iplf-063b:{run}:{index + 1}',
        source_reference=url,
        canonical_url=url,
        content_hash=hashlib.sha256(passage.encode()).hexdigest(),
        source_version='official-v1',
        retrieved_at=datetime.now(UTC) - (timedelta(days=120) if index == 1 else timedelta(days=1)),
        source_access_state='available',
        summary=passage,
        document_text=passage,
        extracted_char_count=len(passage),
        ingested_at=datetime.now(UTC),
    )
    s.add(document)
    s.flush()
    ids.append(document.id)
    urls.append(url)
blocked_text = 'This retained citation is unavailable and must not reach generation.'
blocked = AuthorityDocument(
    source='supreme_court_latest_orders',
    adapter_name='iplf-063b-playwright-v1',
    court_name='Delhi High Court',
    forum_level='high_court',
    document_type='judgment',
    title=f'IPLF 063B inaccessible authority {run}',
    case_reference=f'IPLF 063B BLOCKED/{run}',
    decision_date=date(2026, 8, 22),
    canonical_key=f'iplf-063b:{run}:blocked',
    source_reference=None,
    canonical_url=None,
    content_hash=hashlib.sha256(blocked_text.encode()).hexdigest(),
    source_version='official-v1',
    retrieved_at=datetime.now(UTC),
    source_access_state='unavailable',
    summary=blocked_text,
    document_text=blocked_text,
    extracted_char_count=len(blocked_text),
    ingested_at=datetime.now(UTC),
)
s.add(blocked)
s.commit()
print(json.dumps({'accessibleIds': ids, 'inaccessibleId': blocked.id, 'sourceUrls': urls}))
s.close()
`;
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
  const line = result.stdout
    .trim()
    .split(/\r?\n/)
    .reverse()
    .find((value) => value.trim().startsWith("{"));
  expect(line, result.stdout).toBeTruthy();
  return JSON.parse(line!);
}
