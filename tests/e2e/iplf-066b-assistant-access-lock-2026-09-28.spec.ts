import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./support/env";
import { expectStatus } from "./support/iplf058b";

// Until 2026-09-28 an access change marked a saved Workspace Assistant answer
// for reauthorization, and a document-only answer was served again once its
// author could read the document. The owner decided that an answer locks for
// good after any relevant event, access changes included, and that no read
// saves a decision. This journey changes a Matter's access, restores it, and
// proves the saved answer stays hidden in the browser, after reload, in the
// turn API and for a citation open, while the author can still read the Matter.

const HIDDEN_NOTICE =
  "This answer is hidden because access to one or more cited workspace records changed.";

function pythonExecutable(): string {
  return process.env.CASEOPS_E2E_PYTHON?.trim() ||
    (process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python"));
}

function runPrivateFixture(script: string, values: Record<string, string>): string {
  const result = spawnSync(pythonExecutable(), ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      ...values,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
  return result.stdout.trim().split(/\r?\n/).at(-1) ?? "";
}

type TurnRecord = {
  id: string;
  role: string;
  render_status: string;
  content: string;
  citations: Array<{ id: string }>;
};

test("IPLF-066B an access change and its restore keep a saved assistant answer locked", async ({
  page,
}) => {
  const runId = `${Date.now()}-${randomBytes(4).toString("hex")}`;
  const bootstrap = await page.request.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Assistant Access ${runId}`,
      company_slug: `assistant-access-${runId}`,
      company_type: "law_firm",
      owner_full_name: "Assistant Access Owner",
      owner_email: `assistant-access-${runId}@example.com`,
      owner_password: "AssistantAccess2026!",
    },
  });
  await expectStatus(bootstrap, 200, "assistant access tenant bootstrap");
  const identity = await bootstrap.json();
  const headers = { Authorization: `Bearer ${identity.access_token}` };

  const policy = await page.request.patch(`${apiBaseUrl}/api/admin/tenant-ai-policy`, {
    headers,
    data: {
      expected_version: 1,
      workspace_assistant_enabled: true,
      assistant_retention_days: 30,
      allowed_models_assistant: ["caseops-mock-1"],
    },
  });
  await expectStatus(policy, 200, "enable private assistant policy");
  const colleague = await page.request.post(`${apiBaseUrl}/api/companies/current/users`, {
    headers,
    data: {
      full_name: "Walled Colleague",
      email: `assistant-access-colleague-${runId}@example.com`,
      password: "AssistantColleague2026!",
      role: "member",
    },
  });
  await expectStatus(colleague, 200, "create the colleague the wall excludes");
  const colleagueMembershipId = String((await colleague.json()).membership_id);
  const matter = await page.request.post(`${apiBaseUrl}/api/matters`, {
    headers,
    data: {
      matter_code: `ACCESS-${runId}`,
      title: `Assistant access ${runId}`,
      practice_area: "Intellectual Property",
      forum_level: "high_court",
    },
  });
  await expectStatus(matter, 200, "create assistant access matter");
  const matterRecord = await matter.json();
  const filename = "066B access evidence.txt";
  const secret = `Cobalt-${runId}`;
  runPrivateFixture(
    [
      "import hashlib,os",
      "from sqlalchemy import select",
      "from caseops_api.db.models import BillingSubscription,MatterAttachment,MatterAttachmentChunk",
      "from caseops_api.db.session import get_session_factory",
      "from caseops_api.services.private_retrieval_jobs import rebuild_private_index",
      "s=get_session_factory()()",
      "text=os.environ['CASEOPS_E2E_PRIVATE_TEXT']",
      "digest=hashlib.sha256(text.encode()).hexdigest()",
      "sub=s.scalar(select(BillingSubscription).where(BillingSubscription.company_id==os.environ['CASEOPS_E2E_COMPANY_ID']))",
      "sub=sub or BillingSubscription(company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],status='manual_active',segment='law_firm',source='iplf-066b-e2e',externally_billable=False,entitlement_overrides_json={})",
      "s.add(sub)",
      "sub.entitlement_overrides_json={**(sub.entitlement_overrides_json or {}),'ip_workspace':True}",
      "a=MatterAttachment(matter_id=os.environ['CASEOPS_E2E_MATTER_ID'],uploaded_by_membership_id=os.environ['CASEOPS_E2E_MEMBERSHIP_ID'],original_filename=os.environ['CASEOPS_E2E_FILENAME'],storage_key='iplf-066b-access/'+digest,content_type='text/plain',size_bytes=len(text.encode()),sha256_hex=digest,processing_status='indexed',extracted_char_count=len(text),extracted_text=text)",
      "s.add(a);s.flush()",
      "s.add(MatterAttachmentChunk(attachment_id=a.id,chunk_index=0,content=text,token_count=8))",
      "s.commit();s.close()",
      // Rebuilds require a clean worker session across the provider boundary,
      // exactly as the maintenance job runs them.
      "s=get_session_factory()()",
      "rebuild_private_index(s,company_id=os.environ['CASEOPS_E2E_COMPANY_ID'],activate=True)",
      "s.commit();s.close();print('rebuilt')",
    ].join(";"),
    {
      CASEOPS_E2E_COMPANY_ID: identity.company.id,
      CASEOPS_E2E_MEMBERSHIP_ID: identity.membership.id,
      CASEOPS_E2E_MATTER_ID: matterRecord.id,
      CASEOPS_E2E_FILENAME: filename,
      CASEOPS_E2E_PRIVATE_TEXT: `${secret} is the approved internal renewal evidence.`,
    },
  );

  await page.goto("/");
  await page.evaluate(
    (context) => window.localStorage.setItem("caseops.session.context", JSON.stringify(context)),
    {
      company: identity.company,
      user: identity.user,
      membership: identity.membership,
      capabilities: identity.capabilities,
    },
  );
  await page.goto("/app/assistant");
  await page.getByRole("textbox", { name: "Find workspace records" }).fill("066B access evidence");
  await page.getByRole("button", { name: "Find permitted records" }).click();
  await page.getByRole("button", { name: `Add ${filename}` }).click();
  await page.getByRole("button", { name: "Start conversation" }).click();
  await page
    .getByRole("textbox", { name: "Ask this workspace" })
    .fill(`What does the evidence say about ${secret}?`);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await expect(page.getByTestId("assistant-turns")).toContainText(secret);
  await expect(page.getByRole("link", { name: filename })).toBeVisible();

  // The document-only answer, its citation and its session, as the API holds
  // them. The tenant is new, so its only session is the one just started.
  const sessionsResponse = await page.request.get(
    `${apiBaseUrl}/api/workspace-assistant/sessions`,
    { headers, params: { limit: 10, offset: 0 } },
  );
  await expectStatus(sessionsResponse, 200, "find the assistant session");
  const sessions = (await sessionsResponse.json()).items as Array<{ id: string }>;
  expect(sessions).toHaveLength(1);
  const sessionId = sessions[0].id;
  const readTurns = async (label: string): Promise<TurnRecord[]> => {
    const response = await page.request.get(
      `${apiBaseUrl}/api/workspace-assistant/sessions/${sessionId}/turns`,
      { headers },
    );
    await expectStatus(response, 200, label);
    return (await response.json()).items as TurnRecord[];
  };
  const answered = (await readTurns("read the visible answer")).filter(
    (turn) => turn.role === "assistant",
  );
  expect(answered).toHaveLength(1);
  expect(answered[0].render_status).toBe("visible");
  expect(answered[0].citations).toHaveLength(1);
  const answerId = answered[0].id;
  const citationId = answered[0].citations[0].id;

  // An access change on the answer's Matter, then its restore. The owner who
  // asked never loses access; the wall excludes a colleague and is removed.
  const wall = await page.request.post(
    `${apiBaseUrl}/api/matters/${matterRecord.id}/access/walls`,
    {
      headers,
      data: { excluded_membership_id: colleagueMembershipId, reason: "Temporary conflict check." },
    },
  );
  await expectStatus(wall, 200, "add the ethical wall");
  const wallId = String((await wall.json()).id);
  const removed = await page.request.delete(
    `${apiBaseUrl}/api/matters/${matterRecord.id}/access/walls/${wallId}`,
    { headers },
  );
  await expectStatus(removed, 204, "remove the ethical wall");
  const stillReadable = await page.request.get(`${apiBaseUrl}/api/matters/${matterRecord.id}`, {
    headers,
  });
  await expectStatus(stillReadable, 200, "the author still reads the Matter");

  await page.reload();
  await page.getByRole("button", { name: `Ask · ${filename}`, exact: true }).click();
  await expect(page.getByTestId("assistant-turns")).toContainText(HIDDEN_NOTICE);
  await expect(page.locator('[data-turn-role="assistant"]').last()).not.toContainText(secret);
  await expect(page.getByRole("link", { name: filename })).toHaveCount(0);

  // Every read path makes the same decision, and repeating it changes nothing.
  for (const label of ["first read after the restore", "second read after the restore"]) {
    const answer = (await readTurns(label)).find((turn) => turn.id === answerId);
    expect(answer?.render_status).toBe("permission_changed");
    expect(answer?.citations).toEqual([]);
    expect(answer?.content).not.toContain(secret);
  }
  const exported = await page.request.get(
    `${apiBaseUrl}/api/workspace-assistant/sessions/${sessionId}/export`,
    { headers },
  );
  await expectStatus(exported, 200, "export the session");
  const exportedAnswer = ((await exported.json()).turns as TurnRecord[]).find(
    (turn) => turn.id === answerId,
  );
  expect(exportedAnswer?.render_status).toBe("permission_changed");
  const opened = await page.request.post(
    `${apiBaseUrl}/api/workspace-assistant/sessions/${sessionId}/citations/${citationId}/open`,
    { headers },
  );
  await expectStatus(opened, 409, "the locked answer's citation stays closed");
  await page.reload();
  await page.getByRole("button", { name: `Ask · ${filename}`, exact: true }).click();
  await expect(page.getByTestId("assistant-turns")).toContainText(HIDDEN_NOTICE);

  await page.setViewportSize({ width: 360, height: 800 });
  await expect(page.getByTestId("assistant-turns")).toContainText(HIDDEN_NOTICE);
  await expect(page.getByRole("textbox", { name: "Ask this workspace" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);
});
