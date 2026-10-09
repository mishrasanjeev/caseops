import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { expectStatus } from "./support/iplf058b";

const hiddenNotice =
  "This answer is hidden because access to one or more cited workspace records changed.";

function rebuildLocal(companyId: string, bootstrap = false) {
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(
    repoRoot, "apps", "api", ".venv", process.platform === "win32" ? "Scripts" : "bin",
    process.platform === "win32" ? "python.exe" : "python",
  );
  const script = `
import json, os
from sqlalchemy import select
from sqlalchemy.engine import make_url
from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingSubscription
from caseops_api.db.session import get_session_factory
from caseops_api.services.private_retrieval_jobs import rebuild_private_index, inspect_private_index_integrity
settings = get_settings()
url = make_url(settings.database_url)
assert os.environ['CASEOPS_ENV'] == 'e2e'
assert url.get_backend_name() == 'sqlite' or url.host in ('127.0.0.1', 'localhost', '::1')
assert settings.llm_provider == 'mock' and settings.embedding_provider == 'mock'
company = os.environ['CASEOPS_E2E_WHITESPACE_COMPANY']
if os.environ['CASEOPS_E2E_WHITESPACE_BOOTSTRAP'] == 'true':
    with get_session_factory()() as session:
        sub = session.scalar(select(BillingSubscription).where(BillingSubscription.company_id == company))
        if sub is None:
            sub = BillingSubscription(company_id=company, status='manual_active', segment='law_firm', source='whitespace-local-e2e', externally_billable=False, entitlement_overrides_json={})
            session.add(sub)
        sub.entitlement_overrides_json = {**(sub.entitlement_overrides_json or {}), 'ip_workspace': True}
        session.commit()
with get_session_factory()() as session:
    summary = rebuild_private_index(session, company_id=company, activate=True)
with get_session_factory()() as session:
    report = inspect_private_index_integrity(session, company_id=company)
    assert report.state == 'ready' and not report.blockers
    print(json.dumps({'generation_id': summary.generation_id, 'projection_count': summary.projection_count, 'provider_text_count': summary.provider_text_count, 'stale_source_count': report.stale_source_count, 'blockers': report.blockers}))
`;
  const result = spawnSync(python, ["-B", "-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    timeout: 90_000,
    env: {
      ...process.env, ...e2eEnv,
      PYTHONPATH: path.join(repoRoot, "apps", "api", "src"),
      CASEOPS_E2E_WHITESPACE_COMPANY: companyId,
      CASEOPS_E2E_WHITESPACE_BOOTSTRAP: String(bootstrap),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
  return JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1)!);
}

test("IPLF-UJ-66 multiline sources survive rebuild and reload without reviving invalidated answers", async ({
  page, baseURL,
}, testInfo) => {
  for (const endpoint of [apiBaseUrl, baseURL!]) {
    expect(["127.0.0.1", "localhost", "[::1]"]).toContain(new URL(endpoint).hostname);
  }
  expect(process.env.CASEOPS_LLM_PROVIDER ?? "mock").toBe("mock");
  expect(process.env.CASEOPS_EMBEDDING_PROVIDER ?? "mock").toBe("mock");
  const runId = `${Date.now()}-${randomBytes(4).toString("hex")}`;
  const bootstrap = await page.request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    headers: noPaidProviderHeaders,
    data: {
      company_name: `Whitespace ${runId}`, company_slug: `whitespace-${runId}`,
      company_type: "law_firm", owner_full_name: "Whitespace Owner",
      owner_email: `whitespace-${runId}@example.com`, owner_password: "Whitespace2026!",
    },
  });
  await expectStatus(bootstrap, 200, "bootstrap local whitespace tenant");
  const identity = await bootstrap.json();
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` };
  const policy = await page.request.patch(`${apiBaseUrl}/api/admin/tenant-ai-policy`, {
    headers,
    data: {
      expected_version: 1, workspace_assistant_enabled: true,
      assistant_retention_days: 30, allowed_models_assistant: ["caseops-mock-1"],
    },
  });
  await expectStatus(policy, 200, "enable mock assistant policy");
  const code = `WS-${runId}`;
  const title = `Whitespace matter ${runId}`;
  const evidence = `Cobalt-${runId}`;
  const description = `${evidence}  is approved.\nRetain\tthis evidence.`;
  const created = await page.request.post(`${apiBaseUrl}/api/matters`, {
    headers,
    data: { matter_code: code, title, description, practice_area: "Civil", forum_level: "high_court" },
  });
  await expectStatus(created, 200, "create multiline source");
  const matter = await created.json();
  expect(matter.description).toBe(description);
  const first = rebuildLocal(identity.company.id, true);
  expect(first.stale_source_count).toBe(0);
  expect(first.provider_text_count).toBe(0);

  const search = async () => {
    const response = await page.request.post(`${apiBaseUrl}/api/private-retrieval/search`, {
      headers, data: { query: evidence, source_types: ["matter"], scope_ids: { matter: [matter.id] } },
    });
    await expectStatus(response, 200, "search normalized projection");
    return (await response.json()).items as Array<{ source_id: string; content: string }>;
  };
  expect(await search()).toEqual([expect.objectContaining({
    source_id: matter.id, content: expect.stringContaining(`${evidence} is approved. Retain this evidence.`),
  })]);
  await page.goto("/");
  await page.evaluate((context) => {
    window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
  }, {
    company: identity.company, user: identity.user,
    membership: identity.membership, capabilities: identity.capabilities,
  });
  await page.goto("/app/assistant");
  await page.getByRole("textbox", { name: "Find workspace records" }).fill(code);
  await page.getByRole("button", { name: "Find permitted records" }).click();
  await page.getByRole("button", { name: `Add ${title}`, exact: true }).click();
  await page.getByRole("button", { name: "Start conversation" }).click();
  await page.getByRole("textbox", { name: "Ask this workspace" }).fill(`What evidence mentions ${evidence}?`);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  const answer = page.locator('[data-turn-role="assistant"]').last();
  await expect(answer).toContainText(evidence);
  await expect(page.getByText(/mock · caseops-mock-1/)).toBeVisible();
  const sessions = await page.request.get(`${apiBaseUrl}/api/workspace-assistant/sessions`, { headers });
  await expectStatus(sessions, 200, "read saved conversation");
  const sessionRecords = (await sessions.json()).items;
  expect(sessionRecords).toHaveLength(1);
  const sessionId = sessionRecords[0].id as string;
  const readAnswer = async () => {
    const response = await page.request.get(`${apiBaseUrl}/api/workspace-assistant/sessions/${sessionId}/turns`, { headers });
    await expectStatus(response, 200, "read saved answer");
    return (await response.json()).items.find((turn: { role: string }) => turn.role === "assistant");
  };
  const original = await readAnswer();
  expect(original.render_status).toBe("visible");
  expect(original.citations).toHaveLength(1);
  const citationId = original.citations[0].id;
  const second = rebuildLocal(identity.company.id);
  expect(second.generation_id).not.toBe(first.generation_id);
  for (const width of [1280, 360]) {
    await page.setViewportSize({ width, height: 850 });
    await page.reload();
    await page.getByRole("button", { name: `Ask · ${title}`, exact: true }).click();
    await expect(answer).toContainText(evidence);
    expect((await readAnswer()).render_status).toBe("visible");
    await page.screenshot({ path: testInfo.outputPath(`visible-${width}.png`), fullPage: true });
  }

  const current = await page.request.get(`${apiBaseUrl}/api/matters/${matter.id}`, { headers });
  await expectStatus(current, 200, "read lifecycle version");
  const before = await current.json();
  const disposed = await page.request.patch(`${apiBaseUrl}/api/matters/${matter.id}/lifecycle/status`, {
    headers, data: {
      to_status: "disposed", expected_from_status: before.status,
      expected_updated_at: before.updated_at, reason: "End the whitespace regression engagement.",
    },
  });
  await expectStatus(disposed, 200, "dispose indexed source");
  expect(await search()).toEqual([]);
  expect((await readAnswer()).render_status).toBe("permission_changed");
  const reopened = await page.request.patch(`${apiBaseUrl}/api/matters/${matter.id}/lifecycle/status`, {
    headers, data: {
      to_status: "intake", expected_from_status: "disposed",
      expected_updated_at: (await disposed.json()).updated_at,
      reason: "Explicitly reopen without restoring old assistant evidence.",
    },
  });
  await expectStatus(reopened, 200, "controlled reopening");
  expect(await search()).toEqual([]);
  rebuildLocal(identity.company.id);
  expect(await search()).toHaveLength(1);
  const hidden = await readAnswer();
  expect(hidden.id).toBe(original.id);
  expect(hidden.render_status).toBe("permission_changed");
  expect(hidden.content).not.toContain(evidence);
  expect(hidden.citations).toEqual([]);
  const citation = await page.request.post(
    `${apiBaseUrl}/api/workspace-assistant/sessions/${sessionId}/citations/${citationId}/open`, { headers },
  );
  await expectStatus(citation, 409, "old citation remains revoked after rebuild");
  await page.reload();
  await page.getByRole("button", { name: `Ask · ${title}`, exact: true }).click();
  await expect(answer).toContainText(hiddenNotice);
  await expect(answer).not.toContainText(evidence);
  await expect(page.getByRole("textbox", { name: "Ask this workspace" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("revoked-mobile.png"), fullPage: true });
});
