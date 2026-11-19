import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

import { localTransportHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { runId } from "./support/run-id";

test.use({ trace: "off", screenshot: "off", video: "off" });

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing setup is not a passing skip.`);
  return value;
}
const localHost = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);

for (const mobile of [false, true]) {
  test(`${mobile ? "[mobile] " : ""}AI-TEAM-01 membership and audited lead changes persist after reload`, async ({ page, request, baseURL }, info) => {
    const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
    const local = localHost(web);
    const api = new URL(local
      ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
      : required("PROD_API_BASE_URL"));
    if (web.username || web.password || api.username || api.password || local !== localHost(api)
      || ![web, api].every((url) => ["http:", "https:"].includes(url.protocol))
      || (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai"))) {
      throw new Error("Requirements acceptance requires loopback or the canonical production pair.");
    }
    const sha = local ? e2eEnv.CASEOPS_RELEASE_SHA : required("CASEOPS_EXPECTED_RELEASE_SHA");
    const release = () => assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
    await release();
    const transport = localTransportHeaders(api.origin);
    const nonce = runId();
    const credentials = local
      ? { slug: `ai-req-${nonce}`, email: `qa-${nonce}@example.com`, password: `Synthetic!${randomUUID()}` }
      : { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"), password: required("CASEOPS_RAM_PROD_PASSWORD") };
    if (!local && credentials.slug !== "test-legal") throw new Error("Production requirements acceptance is test-legal only.");
    if (local) {
      const bootstrap = await request.post(`${api.origin}/api/bootstrap/company`, { headers: transport, data: {
        company_name: "Requirements QA", company_slug: credentials.slug, company_type: "law_firm",
        owner_full_name: "Requirements QA", owner_email: credentials.email, owner_password: credentials.password,
      } });
      expect(bootstrap.status(), "Loopback tenant bootstrap").toBe(200);
    }
    const login = await request.post(`${api.origin}/api/auth/login`, { headers: transport,
      data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
    expect(login.status(), "Requirements API authentication").toBe(200);
    const actor = await login.json() as { access_token: string; company: { slug: string }; membership: { id: string } };
    expect(actor.company.slug).toBe(credentials.slug);
    const headers = { ...transport, Authorization: `Bearer ${actor.access_token}` };
    const directoryResponse = await request.get(`${api.origin}/api/companies/current/users`, { headers });
    expect(directoryResponse.status(), "Read authorized tenant directory").toBe(200);
    const directory = await directoryResponse.json() as { users: Array<{ membership_id: string; full_name: string }> };
    const self = directory.users.find((user) => user.membership_id === actor.membership.id);
    expect(self, "Authenticated actor must be an available tenant colleague").toBeTruthy();
    const started = new Date(Date.now() - 60_000).toISOString();
    const teamName = `Requirements QA ${nonce}`;
    const teamSlug = `ai-req-${nonce}`;
    let teamId: string | undefined;
    await page.setViewportSize(mobile ? { width: 393, height: 851 } : { width: 1280, height: 900 });
    await page.setExtraHTTPHeaders(localTransportHeaders(web.origin));
    await page.goto(`${web.origin}/sign-in`);
    await page.locator("#company-slug").fill(credentials.slug);
    await page.locator("#email").fill(credentials.email);
    await page.locator("#password").fill(credentials.password);
    await page.getByRole("button", { name: /^Sign in$/ }).click();
    await page.waitForURL(/\/app(?:[/?]|$)/);
    let diagnosticStage = "team-enter";
    let diagnosticBodyCompleted = false;
    try {
      diagnosticStage = "team-source-line-72";
      await page.goto(`${web.origin}/app/admin/teams`);
      diagnosticStage = "team-source-line-73";
      await page.getByTestId("new-team-trigger").first().click();
      const create = page.getByRole("dialog", { name: "Create a team" });
      diagnosticStage = "team-source-line-75";
      await create.getByLabel("Name", { exact: true }).fill(teamName);
      diagnosticStage = "team-source-line-76";
      await create.getByLabel("Slug", { exact: true }).fill(teamSlug);
      const created = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/teams/" && response.request().method() === "POST");
      diagnosticStage = "team-source-line-78";
      await create.getByRole("button", { name: "Create team", exact: true }).click();
      diagnosticStage = "team-source-line-79";
      const createdResponse = await created;
      expect(createdResponse.status(), "UI-created team").toBe(201);
      teamId = (await createdResponse.json() as { id: string }).id;
      expect(teamId).toMatch(/^[a-f0-9-]{36}$/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "Teams row stays within its available width").toBe(true);
      diagnosticStage = "team-source-line-84";
      await page.getByRole("button", { name: `Manage members of ${teamName}` }).click();
      let dialog = page.getByRole("dialog", { name: `Members of ${teamName}` });
      const colleague = dialog.getByRole("combobox", { name: "Colleague" });
      diagnosticStage = "team-source-line-87";
      await colleague.selectOption(actor.membership.id);
      const membersPath = `/api/teams/${teamId}/members`;
      const removalPath = `${membersPath}/${actor.membership.id}`;
      const saved = (path: string, method: string) => page.waitForResponse(
        (response) => new URL(response.url()).pathname === path && response.request().method() === method,
      );
      const readRowId = async (response: { json(): Promise<unknown> }) =>
        (await response.json() as { members: [{ id: string }] }).members[0].id;
      let response = saved(membersPath, "POST");
      diagnosticStage = "team-source-line-96";
      await dialog.getByRole("button", { name: "Add member", exact: true }).click();
      diagnosticStage = "team-source-line-97";
      const add = await response;
      expect(add.status(), "Add through membership UI").toBe(200);
      diagnosticStage = "team-source-line-99";
      const originalId = await readRowId(add);
      const leadPath = (rowId: string) => `${membersPath}/${rowId}/lead`;
      const leadName = `Team lead for ${self!.full_name}`;
      diagnosticStage = "team-source-line-102";
      await expect(dialog.getByRole("checkbox", { name: leadName })).not.toBeChecked();
      response = saved(leadPath(originalId), "PATCH");
      diagnosticStage = "team-source-line-104";
      await dialog.getByRole("checkbox", { name: leadName }).check();
      expect((await response).status(), "Promote through membership UI").toBe(200);
      diagnosticStage = "team-source-line-106";
      await expect(dialog.getByRole("checkbox", { name: leadName })).toBeChecked();
      diagnosticStage = "team-source-line-107";
      await expect(dialog.getByRole("checkbox", { name: leadName })).toBeEnabled();
      response = saved(leadPath(originalId), "PATCH");
      diagnosticStage = "team-source-line-109";
      await dialog.getByRole("checkbox", { name: leadName }).uncheck();
      expect((await response).status(), "Demote through membership UI").toBe(200);
      diagnosticStage = "team-source-line-111";
      const replay = await request.patch(`${api.origin}${leadPath(originalId)}`, { headers, data: { is_lead: false } });
      expect(replay.status(), "Identical membership replay").toBe(200);
      diagnosticStage = "team-source-line-113";
      await page.reload();
      diagnosticStage = "team-source-line-114";
      await page.getByRole("button", { name: `Manage members of ${teamName}` }).click();
      dialog = page.getByRole("dialog", { name: `Members of ${teamName}` });
      diagnosticStage = "team-source-line-116";
      await expect(dialog.getByRole("checkbox", { name: leadName })).not.toBeChecked();
      for (const control of [dialog.getByRole("checkbox", { name: leadName }), dialog.getByRole("button", { name: `Remove ${self!.full_name} from team` })]) {
        diagnosticStage = "team-source-line-118";
        const box = await control.boundingBox();
        expect(box, "Visible membership control").not.toBeNull();
        expect(box!.width).toBeGreaterThan(12);
        expect(box!.x).toBeGreaterThanOrEqual(0);
        expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
      }
      const auditParams = new URLSearchParams({ action: "team_membership.updated", since: started, limit: "50", format: "jsonl" });
      const readLeadAudits = async () => {
        diagnosticStage = "team-source-line-126";
        const result = await request.get(`${api.origin}/api/admin/audit/export?${auditParams}`, { headers });
        expect(result.status(), "Read persisted membership audit").toBe(200);
        diagnosticStage = "team-source-line-128";
        return (await result.text()).trim().split(/\r?\n/).filter(Boolean).map((line) => JSON.parse(line))
          .filter((event) => event.metadata?.team_id === teamId);
      };
      diagnosticStage = "team-source-line-131";
      const audits = await readLeadAudits();
      expect(audits.map((event) => [event.metadata.before.is_lead, event.metadata.after.is_lead])).toEqual([[false, true], [true, false]]);
      expect(audits.every((event) => event.actor_membership_id === actor.membership.id)).toBe(true);

      const removeElsewhere = async () => {
        diagnosticStage = "team-source-line-136";
        const result = await request.delete(`${api.origin}${removalPath}`, { headers });
        expect(result.status(), "Concurrent removal via legacy DELETE").toBe(200);
        expect((await result.json()).members).toEqual([]);
      };
      const addElsewhere = async () => {
        diagnosticStage = "team-source-line-141";
        const result = await request.post(`${api.origin}${membersPath}`, {
          headers, data: { membership_id: actor.membership.id, is_lead: false },
        });
        expect(result.status(), "Concurrent replacement via add").toBe(200);
        return readRowId(result);
      };
      const rejectStaleLead = async (rowId: string) => {
        const checkbox = dialog.getByRole("checkbox", { name: leadName });
        diagnosticStage = "team-source-line-149";
        await expect(checkbox).not.toBeChecked();
        const stale = saved(leadPath(rowId), "PATCH");
        // check() requires a checked final state, but this stale command must roll back.
        diagnosticStage = "team-source-line-152";
        await checkbox.press("Space");
        diagnosticStage = "team-source-line-153";
        const result = await stale;
        expect(result.request().postDataJSON()).toEqual({ is_lead: true });
        expect(result.status(), "Stale lead change is update-only").toBe(409);
        expect((await result.json()).code).toBe("team_membership_changed");
        diagnosticStage = "team-source-line-157";
        await expect(dialog.getByRole("alert")).toContainText("This team membership changed.");
      };
      diagnosticStage = "team-source-line-159";
      await removeElsewhere();
      diagnosticStage = "team-source-line-160";
      await rejectStaleLead(originalId);
      diagnosticStage = "team-source-line-161";
      await expect(dialog.getByText("No members yet.", { exact: true })).toBeVisible();

      diagnosticStage = "team-source-line-163";
      await dialog.getByRole("combobox", { name: "Colleague" }).selectOption(actor.membership.id);
      response = saved(membersPath, "POST");
      diagnosticStage = "team-source-line-165";
      await dialog.getByRole("button", { name: "Add member", exact: true }).click();
      diagnosticStage = "team-source-line-166";
      const readded = await response;
      expect(readded.status()).toBe(200);
      diagnosticStage = "team-source-line-168";
      const observedId = await readRowId(readded);
      expect(observedId).not.toBe(originalId);
      diagnosticStage = "team-source-line-170";
      await expect(dialog.getByRole("checkbox", { name: leadName })).toBeEnabled();
      diagnosticStage = "team-source-line-171";
      await removeElsewhere();
      diagnosticStage = "team-source-line-172";
      const replacementId = await addElsewhere();
      expect(replacementId).not.toBe(observedId);
      diagnosticStage = "team-source-line-174";
      await rejectStaleLead(observedId);
      diagnosticStage = "team-source-line-175";
      await expect(dialog.getByRole("checkbox", { name: leadName })).not.toBeChecked();

      const promptRemoval = async () => {
        diagnosticStage = "team-source-line-178";
        await dialog.getByRole("button", { name: `Remove ${self!.full_name} from team` }).click();
        diagnosticStage = "team-source-line-179";
        await expect(dialog.getByRole("group", { name: `Confirm removal of ${self!.full_name}` })).toBeVisible();
      };
      diagnosticStage = "team-source-line-181";
      await promptRemoval();
      diagnosticStage = "team-source-line-182";
      await removeElsewhere();
      diagnosticStage = "team-source-line-183";
      const finalId = await addElsewhere();
      expect(finalId).not.toBe(replacementId);
      response = saved(removalPath, "DELETE");
      diagnosticStage = "team-source-line-186";
      await dialog.getByRole("button", { name: "Remove member", exact: true }).click();
      diagnosticStage = "team-source-line-187";
      const staleRemoval = await response;
      expect(new URL(staleRemoval.url()).searchParams.get("expected_team_membership_id")).toBe(replacementId);
      expect(staleRemoval.status(), "Old confirmation cannot delete the replacement").toBe(409);
      expect((await staleRemoval.json()).code).toBe("team_membership_changed");
      diagnosticStage = "team-source-line-191";
      await expect(dialog.getByRole("button", { name: "Remove member", exact: true })).toHaveCount(0);
      diagnosticStage = "team-source-line-192";
      await expect(dialog.getByRole("alert")).toContainText("This team membership changed.");
      diagnosticStage = "team-source-line-193";
      await expect(dialog.getByRole("checkbox", { name: leadName })).not.toBeChecked();
      expect(await readLeadAudits()).toEqual(audits);

      diagnosticStage = "team-source-line-196";
      await promptRemoval();
      const removed = saved(removalPath, "DELETE");
      diagnosticStage = "team-source-line-198";
      await dialog.getByRole("button", { name: "Remove member", exact: true }).click();
      diagnosticStage = "team-source-line-199";
      const confirmedRemoval = await removed;
      expect(new URL(confirmedRemoval.url()).searchParams.get("expected_team_membership_id")).toBe(finalId);
      expect(confirmedRemoval.status(), "Confirmed membership removal").toBe(200);
      diagnosticStage = "team-source-line-202";
      await expect(dialog.getByRole("checkbox", { name: leadName })).toHaveCount(0);
      diagnosticStage = "team-source-line-203";
      await page.reload();
      diagnosticStage = "team-source-line-204";
      await page.getByRole("button", { name: `Manage members of ${teamName}` }).click();
      diagnosticStage = "team-source-line-205";
      await expect(page.getByRole("dialog", { name: `Members of ${teamName}` }).getByText("No members yet.", { exact: true })).toBeVisible();
      diagnosticStage = "team-source-line-206";
      await release();
      diagnosticBodyCompleted = true;
    } finally {
      info.annotations.push({ type: "caseops-b5-team-body", description: `${diagnosticStage}:completed-${diagnosticBodyCompleted}` });
      if (teamId) {
        const cleanup = await request.delete(`${api.origin}/api/teams/${teamId}`, { headers });
        expect(cleanup.status(), "Remove only the team created by this execution").toBe(204);
      }
    }
  });
}
