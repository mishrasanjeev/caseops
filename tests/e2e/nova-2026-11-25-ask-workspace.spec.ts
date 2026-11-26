/**
 * Tester workbook dated 25 Nov 2026, row 3 (nova-legal): Ask Workspace refused
 * Matter questions about the parties, pending actions, documents and the
 * sections of the Hindu Marriage Act with a generic "not enough evidence" reply.
 *
 * The journey signs in as the tester through the sign-in page, uses its own
 * uniquely named Matter with a task and a hearing created through the Matter's
 * own pages, selects that Matter in Ask Workspace, asks the reported questions
 * and checks that each reply is a specific answer that cites the Matter record
 * it came from. API calls are oracles only, plus the loopback-only Matter seed.
 * Every request carries the no-paid-provider marker, so the assistant answers
 * with the deterministic offline provider in every environment.
 *
 * Production runs need CASEOPS_EXPECTED_RELEASE_SHA and the tester's
 * credentials in CASEOPS_NOVA_PROD_EMAIL / CASEOPS_NOVA_PROD_PASSWORD (never
 * committed). Missing setup fails; nothing here skips. The Matter it created is
 * disposed (which closes its task and hearing) and the conversation archived.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";
import { disposeMatter } from "./support/retire-records";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const GENERIC_REFUSAL = "I do not have enough permitted, verified evidence to answer that safely.";
const HMA_QUESTION = "Explain the relevant sections of the Hindu Marriage Act, 1955";
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  /** API oracle headers. UI journeys never use them to act as the user. */
  headers: Record<string, string>;
  release: () => Promise<void>;
};
type Citation = { id: string; source_type: string; source_id: string; source_url: string | null; label: string };
type Action = { action_type: string; href: string | null; requires_confirmation: boolean; label: string };
type AssistantTurn = {
  id: string;
  status: string;
  content: string;
  render_status: string;
  citations: Citation[];
  proposed_actions: Action[];
  model: { provider: string } | null;
};
type AssistantSession = { id: string; title: string; version: number; scopes: { scope_type: string; scope_id: string }[] };
type AskResponse = { session: AssistantSession; assistant_turn: AssistantTurn };

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

async function runtime(baseURL: string | undefined, request: APIRequestContext): Promise<Runtime> {
  const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
  const local = loopback(web);
  const api = new URL(local ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
    : required("PROD_API_BASE_URL"));
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Remote acceptance requires the canonical production origins.");
  }
  const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  const release = () => assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  await release();
  const credentials: TesterCredentials = local
    ? {
      slug: process.env.CASEOPS_NOVA_LOCAL_SLUG?.trim() || `nov25-nova-${randomUUID()}`,
      email: process.env.CASEOPS_NOVA_LOCAL_EMAIL?.trim() || `nova-${randomUUID()}@example.com`,
      password: process.env.CASEOPS_NOVA_LOCAL_PASSWORD?.trim() || `Synthetic!${randomUUID()}`,
    }
    : { slug: process.env.CASEOPS_NOVA_PROD_SLUG?.trim() || "nova-legal", email: required("CASEOPS_NOVA_PROD_EMAIL"),
      password: required("CASEOPS_NOVA_PROD_PASSWORD") };
  if (!local && credentials.slug !== "nova-legal") {
    throw new Error("Production acceptance runs only in the reporting tester's own workspace.");
  }
  const login = () => request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
  let response = await login();
  if (local && response.status() !== 200) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Nova Legal Associates", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Riya Gupta", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    response = await login();
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(response, "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  return { web, api, local, credentials,
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` }, release };
}

/** Production never rewrites the tester's AI policy; loopback enables its fresh tenant. */
async function assistantPolicy(request: APIRequestContext, rt: Runtime) {
  const policy = await json<{ policy_version: number; workspace_assistant_enabled: boolean;
    assistant_retention_days: number }>(await request.get(`${rt.api.origin}/api/admin/tenant-ai-policy`,
    { headers: rt.headers }), "Read the assistant policy");
  if (policy.workspace_assistant_enabled) return;
  if (!rt.local) throw new Error("Ask Workspace must already be enabled in nova-legal; this spec never rewrites it.");
  await json(await request.patch(`${rt.api.origin}/api/admin/tenant-ai-policy`, { headers: rt.headers, data: {
    expected_version: policy.policy_version, workspace_assistant_enabled: true,
    allowed_models_assistant: ["caseops-mock-1"], assistant_retention_days: policy.assistant_retention_days,
  } }), "Enable the loopback tenant's assistant");
}

async function createMatterThroughUi(page: Page, rt: Runtime, matter: {
  title: string; code: string; client: string; opposing: string;
}): Promise<string> {
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog", { name: "New matter" });
  await dialog.getByLabel("Title", { exact: true }).fill(matter.title);
  await dialog.getByLabel("Matter code", { exact: true }).fill(matter.code);
  await dialog.getByLabel("Practice area", { exact: true }).fill("Family Law");
  await dialog.getByLabel("Client name", { exact: true }).fill(matter.client);
  await dialog.getByLabel("Opposing party", { exact: true }).fill(matter.opposing);
  const created = page.waitForResponse((r) => r.request().method() === "POST"
    && new URL(r.url()).pathname === "/api/matters/");
  await dialog.getByRole("button", { name: "Create matter", exact: true }).click();
  return (await json<{ id: string }>(await created, "Create the journey's Matter through the UI")).id;
}

test("row 3 Ask Workspace answers parties, pending actions, documents and Act sections from the cited Matter record", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const rt = await runtime(baseURL, request);
  await page.setViewportSize({ width: 1365, height: 900 });
  await assistantPolicy(request, rt);
  const nonce = randomUUID().slice(0, 8).toUpperCase();
  const matter = {
    title: stamp(`Nov25 Ask Workspace ${nonce}`),
    code: `NOV25-AW-${nonce}`,
    client: `Priya Desai ${nonce}`,
    opposing: `Akash Desai ${nonce}`,
  };
  const taskTitle = stamp("Nov25 file the maintenance reply");
  const hearingPurpose = `Nov25 mediation report ${nonce}`;
  const today = (await json<{ today: string }>(await request.get(`${rt.api.origin}/api/me/today`,
    { headers: rt.headers }), "Today oracle")).today;
  const due = new Date(`${today}T00:00:00Z`);
  due.setUTCDate(due.getUTCDate() + 14);
  const hearingOn = new Date(`${today}T00:00:00Z`);
  hearingOn.setUTCDate(hearingOn.getUTCDate() + 30);
  const iso = (value: Date) => value.toISOString().slice(0, 10);

  let matterId: string | undefined;
  let conversationId: string | undefined;
  try {
    if (rt.local) {
      // Loopback-only seed; production creates the Matter through the UI below.
      matterId = (await json<{ id: string }>(await request.post(`${rt.api.origin}/api/matters/`, {
        headers: rt.headers, data: { matter_code: matter.code, title: matter.title, practice_area: "Family Law",
          forum_level: "lower_court", client_name: matter.client, opposing_party: matter.opposing },
      }), "Local seed Matter")).id;
      await signIn(page, { web: rt.web }, rt.credentials);
    } else {
      await signIn(page, { web: rt.web }, rt.credentials);
      matterId = await createMatterThroughUi(page, rt, matter);
    }
    const id = matterId;

    // A task through the Matter's Tasks page.
    await page.goto(`${rt.web.origin}/app/matters/${id}/tasks`);
    const taskForm = page.locator("form").filter({ has: page.getByLabel("Task", { exact: true }) });
    await taskForm.getByLabel("Task", { exact: true }).fill(taskTitle);
    await taskForm.getByLabel("Due").fill(iso(due));
    const createdTask = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname === `/api/matters/${id}/tasks`);
    await taskForm.getByRole("button", { name: /Add/ }).click();
    await json(await createdTask, "Create the task through the Tasks page");

    // A hearing through the Matter's Hearings page.
    await page.goto(`${rt.web.origin}/app/matters/${id}/hearings`);
    await page.getByTestId("schedule-hearing-open").first().click();
    const hearingDialog = page.getByRole("dialog", { name: "Schedule a hearing" });
    await hearingDialog.getByTestId("schedule-hearing-date").fill(iso(hearingOn));
    await hearingDialog.locator("#forum_name").fill("Family Court Pune");
    await hearingDialog.locator("#purpose").fill(hearingPurpose);
    const createdHearing = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname === `/api/matters/${id}/hearings`);
    await hearingDialog.getByTestId("schedule-hearing-submit").click();
    expect([200, 201]).toContain((await createdHearing).status());

    // Select the Matter in Ask Workspace.
    await page.goto(`${rt.web.origin}/app/assistant`);
    await expect(page.getByRole("heading", { name: "Ask this Workspace", exact: true })).toBeVisible();
    await page.getByRole("textbox", { name: "Find workspace records", exact: true }).fill(matter.code);
    await page.getByRole("button", { name: "Find permitted records", exact: true }).click();
    await page.getByRole("button", { name: `Add ${matter.title}`, exact: true }).click();
    const starting = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname === "/api/workspace-assistant/sessions");
    await page.getByRole("button", { name: "Start conversation", exact: true }).click();
    const conversation = await json<AssistantSession>(await starting, "Start the Matter-scoped conversation", 201);
    conversationId = conversation.id;
    expect(conversation.scopes).toEqual([expect.objectContaining({ scope_type: "matter", scope_id: id })]);

    async function ask(question: string) {
      await page.getByRole("textbox", { name: "Ask this workspace", exact: true }).fill(question);
      const answering = page.waitForResponse((r) => r.request().method() === "POST"
        && new URL(r.url()).pathname === `/api/workspace-assistant/sessions/${conversationId}/ask`);
      await page.getByRole("button", { name: "Ask", exact: true }).click();
      const answer = await json<AskResponse>(await answering, `Ask: ${question}`);
      const turn = answer.assistant_turn;
      const article = page.locator(`[data-turn-id="${turn.id}"][data-turn-role="assistant"]`);
      await expect(article).toBeVisible();
      await expect(article).toContainText(turn.content.slice(0, 60));
      expect(turn.render_status).toBe("visible");
      expect(turn.content).not.toBe(GENERIC_REFUSAL);
      expect(turn.status, `${question} is answered from the Matter record`).toBe("completed");
      for (const citation of turn.citations) expect(citation.source_id).toBe(id);
      return { turn, article };
    }
    const kinds = (turn: AssistantTurn) => turn.citations.map((citation) => citation.source_type);

    const parties = await ask("Who are the parties involved in this matter?");
    expect(kinds(parties.turn)).toContain("matter_parties");
    expect(parties.turn.content).toContain(matter.opposing);
    await expect(parties.article.getByRole("link", { name: "Search verified legal sources" })).toHaveCount(0);

    const pending = await ask("Are there any pending actions before the next hearing?");
    expect(kinds(pending.turn)).toContain("matter_tasks");
    expect(pending.turn.content).toContain(taskTitle);
    expect(pending.turn.proposed_actions.filter((action) => action.action_type === "search")).toEqual([]);
    await expect(pending.article.getByRole("link", { name: "Search verified legal sources" })).toHaveCount(0);
    const tasksSource = pending.turn.citations.find((citation) => citation.source_type === "matter_tasks")!;
    expect(tasksSource.source_url).toBe(`/app/matters/${id}/tasks`);
    const opening = page.waitForResponse((r) => r.request().method() === "POST"
      && new URL(r.url()).pathname.endsWith(`/citations/${tasksSource.id}/open`));
    await pending.article.getByRole("button", { name: `Open source: ${tasksSource.label}`, exact: true }).click();
    expect((await json<{ source_url: string }>(await opening, "Open the tasks citation")).source_url)
      .toBe(`/app/matters/${id}/tasks`);
    await expect(page).toHaveURL(new RegExp(`/app/matters/${id}/tasks(?:[?#]|$)`));
    await expect(page.getByText(taskTitle)).toBeVisible();
    await page.goto(`${rt.web.origin}/app/assistant`);
    await page.getByRole("button", { name: conversation.title, exact: true }).click();

    const documents = await ask("List all documents available in this matter.");
    expect(kinds(documents.turn)).toContain("matter_documents");
    expect(documents.turn.content).toContain("Documents in this matter: 0");

    const statutes = await ask(HMA_QUESTION);
    expect(statutes.turn.model, "A statute question is never sent to a model").toBeNull();
    expect(kinds(statutes.turn)).toEqual(["matter_statutes"]);
    expect(statutes.turn.content).toContain("I cannot explain or interpret statutory provisions here.");
    expect(statutes.turn.content).toContain("Linked sections: none recorded.");
    const handoff = statutes.turn.proposed_actions.filter((action) => action.action_type === "search");
    expect(handoff).toHaveLength(1);
    const destination = new URL(handoff[0].href!, rt.web.origin);
    expect(destination.pathname).toBe("/app/research");
    expect(destination.searchParams.get("query")).toBe(HMA_QUESTION);
    expect(destination.searchParams.get("matter")).toBe(id);
    const link = statutes.article.getByRole("link", { name: "Search verified legal sources", exact: true });
    expect(await link.getAttribute("href")).toBe(handoff[0].href);
    await link.click();
    await expect(page).toHaveURL(new RegExp(`/app/research\\?query=.*&matter=${id}$`));
    await expect(page.getByText("Using the recorded facts of matter")).toBeVisible();
  } finally {
    // Retire what this run created, each step independently.
    const failures: string[] = [];
    if (conversationId) {
      try {
        const current = await json<AssistantSession>(await request.get(
          `${rt.api.origin}/api/workspace-assistant/sessions/${conversationId}`, { headers: rt.headers }),
        "Read the journey's conversation");
        await json(await request.post(`${rt.api.origin}/api/workspace-assistant/sessions/${conversationId}/archive`,
          { headers: rt.headers, data: { expected_version: current.version } }), "Archive the journey's conversation");
      } catch (error) {
        failures.push(`conversation ${conversationId}: ${(error as Error).message.split("\n")[0]}`);
      }
    }
    if (matterId) {
      try {
        await disposeMatter(request, rt.api.origin, rt.headers, matterId,
          "Nov 25 Ask Workspace acceptance cleanup; synthetic Matter created by this run.");
      } catch (error) {
        failures.push(`matter ${matterId}: ${(error as Error).message.split("\n")[0]}`);
      }
    }
    if (failures.length) throw new Error(`Could not retire created records: ${failures.join("; ")}`);
  }
  await rt.release();
});
