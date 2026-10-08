import { expect, type Page } from "@playwright/test";
import { noPaidProviderHeaders } from "./cost-controls";
import { expectStatus } from "./iplf058b";

type Fixture = {
  id: string;
  matter_code: string;
  title: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  updated_at: string;
};

export function selectPrivateReleaseFixture<T extends Fixture>(rows: T[], prefix: string): T {
  if (!/^IPLF-066B-[A-F0-9]{12}$/.test(prefix)) throw new Error("Invalid release fixture prefix.");
  if (!rows.length) throw new Error("The exact-release private fixture is missing.");
  const ranked = rows.map((row) => {
    const suffix = row.matter_code.slice(prefix.length);
    if (!row.matter_code.startsWith(prefix) || (suffix && !/^-R(?:[2-9]|[1-9][0-9]+)$/.test(suffix))) {
      throw new Error("Refusing a colliding release fixture.");
    }
    if (!["active", "disposed"].includes(row.status)) throw new Error("Unexpected fixture lifecycle.");
    return { row, iteration: suffix ? Number(suffix.slice(2)) : 1 };
  });
  const active = ranked.filter(({ row }) => row.status === "active");
  if (active.length > 1) throw new Error("The active release fixture is ambiguous.");
  if (active.length === 1) return active[0].row;
  ranked.sort((a, b) => b.iteration - a.iteration);
  if (ranked.length > 1 && ranked[0].iteration === ranked[1].iteration) {
    throw new Error("The retired release fixture is ambiguous.");
  }
  return ranked[0].row;
}

type RetainedTurn = {
  role: string;
  render_status: string;
  content: string;
  citations: unknown[];
  proposed_actions: unknown[];
};

export function assertRevokedTurns(turns: RetainedTurn[], evidenceToken: string): void {
  const answers = turns.filter((turn) => turn.role === "assistant");
  expect(answers.length, "retained evidence must contain an actual prior answer").toBeGreaterThan(0);
  for (const answer of answers) {
    expect(answer.render_status).toBe("permission_changed");
    expect(answer.content).not.toContain(evidenceToken);
    expect(answer.citations).toEqual([]);
    expect(answer.proposed_actions).toEqual([]);
  }
}

export async function verifyRetainedPrivateRevocation(
  page: Page,
  input: {
    api: string; web: string; headers: Record<string, string>;
    matter: Fixture; filename: string; evidenceToken: string;
  },
): Promise<void> {
  const { api, web, matter, filename, evidenceToken } = input;
  const headers = { ...input.headers, ...noPaidProviderHeaders };
  expect(matter.status).toBe("disposed");
  const initialResponse = await page.request.get(`${api}/api/matters/${matter.id}`, { headers });
  await expectStatus(initialResponse, 200, "read retained terminal source before revocation proof");
  const initial = await initialResponse.json();
  expect(initial).toMatchObject({
    id: matter.id, matter_code: matter.matter_code, status: "disposed", is_active: false,
    updated_at: matter.updated_at,
  });
  const sessionsResponse = await page.request.get(`${api}/api/workspace-assistant/sessions`, {
    headers,
    params: { title: `Ask \u00b7 ${filename}`, limit: 100, offset: 0 },
  });
  await expectStatus(sessionsResponse, 200, "read exact retained QA sessions");
  const body = await sessionsResponse.json();
  expect(body.has_more, "exact retained-session lookup must remain bounded").toBe(false);
  const matches = body.items as Array<{ id: string; title: string }>;
  expect(matches.length, "a retired fixture needs retained answer evidence").toBeGreaterThan(0);
  for (const session of matches) {
    const response = await page.request.get(`${api}/api/workspace-assistant/sessions/${session.id}/turns`, { headers });
    await expectStatus(response, 200, "reauthorize retained private answer");
    const body = await response.json();
    expect(body.has_more, "QA conversation must remain bounded").toBe(false);
    assertRevokedTurns(body.items, evidenceToken);
    const exported = await page.request.get(`${api}/api/workspace-assistant/sessions/${session.id}/export`, { headers });
    await expectStatus(exported, 200, "reauthorize retained answer export");
    assertRevokedTurns((await exported.json()).turns, evidenceToken);
  }
  // Metadata and documents have independent projections; neither may survive disposal.
  for (const source of [
    { sourceType: "matter_document", query: evidenceToken },
    { sourceType: "matter", query: matter.matter_code },
  ]) {
    const filters = { query: source.query, source_types: [source.sourceType], scope_ids: { matter: [matter.id] }, limit: 10 };
    for (const endpoint of ["search", "autocomplete", "count"]) {
      const response = await page.request.post(`${api}/api/private-retrieval/${endpoint}`, { headers, data: filters });
      await expectStatus(response, 200, `retained ${source.sourceType} revocation ${endpoint}`);
      const body = await response.json();
      if (endpoint === "count") expect(body).toMatchObject({ visible_match_count: 0, count_is_capped: false });
      else expect(body.items).toEqual([]);
    }
  }
  for (const width of [1280, 360]) {
    await page.setViewportSize({ width, height: 800 });
    await page.goto(`${web}/app/assistant`);
    for (const query of [filename, matter.matter_code]) {
      await page.getByRole("textbox", { name: "Find workspace records" }).fill(query);
      const scopeResponse = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname === "/api/workspace-assistant/scope-options"
          && url.searchParams.get("q") === query;
      });
      await page.getByRole("button", { name: "Find permitted records" }).click();
      const response = await scopeResponse;
      await expectStatus(response, 200, "terminal documents and metadata stay out of scope discovery");
      expect(await response.request().headerValue("X-CaseOps-Automated-Test")).toBe("no-paid-providers");
      expect((await response.json()).items).toEqual([]);
      for (const label of [filename, matter.title]) {
        await expect(page.getByRole("button", { name: `Add ${label}`, exact: true })).toHaveCount(0);
      }
    }
    expect(await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    )).toBe(false);
  }
  const persisted = await page.request.get(`${api}/api/matters/${matter.id}`, { headers });
  await expectStatus(persisted, 200, "terminal fixture remains unchanged");
  const final = await persisted.json();
  expect(final).toEqual(initial);
}
