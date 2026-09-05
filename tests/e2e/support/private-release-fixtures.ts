import { expect, type Page } from "@playwright/test";
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
  const { api, web, headers, matter, filename, evidenceToken } = input;
  expect(matter.status).toBe("disposed");
  const matches: Array<{ id: string; title: string }> = [];
  for (let offset = 0; offset < 500; offset += 100) {
    const response = await page.request.get(`${api}/api/workspace-assistant/sessions`, {
      headers, params: { limit: 100, offset },
    });
    await expectStatus(response, 200, "read bounded retained QA sessions");
    const body = await response.json();
    matches.push(...body.items.filter((item: { title: string }) => item.title === `Ask \u00b7 ${filename}`));
    if (!body.has_more) break;
    expect(offset, "retained-session scan exceeded its bound").toBeLessThan(400);
  }
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
  const filters = { query: evidenceToken, source_types: ["matter_document"], scope_ids: { matter: [matter.id] }, limit: 10 };
  for (const endpoint of ["search", "autocomplete", "count"]) {
    const response = await page.request.post(`${api}/api/private-retrieval/${endpoint}`, { headers, data: filters });
    await expectStatus(response, 200, `retained revocation ${endpoint}`);
    const body = await response.json();
    if (endpoint === "count") expect(body.visible_match_count).toBe(0);
    else expect(body.items).toEqual([]);
  }
  await page.goto(`${web}/app/assistant`);
  await page.setViewportSize({ width: 360, height: 800 });
  await page.getByRole("textbox", { name: "Find workspace records" }).fill(filename);
  const scopeResponse = page.waitForResponse((response) => response.url().includes("/api/workspace-assistant/scope-options?"));
  await page.getByRole("button", { name: "Find permitted records" }).click();
  const response = await scopeResponse;
  expect(response.status()).toBe(200);
  expect((await response.json()).items).toEqual([]);
  await expect(page.getByRole("button", { name: `Add ${filename}` })).toHaveCount(0);
  const persisted = await page.request.get(`${api}/api/matters/${matter.id}`, { headers });
  await expectStatus(persisted, 200, "terminal fixture remains unchanged");
  const final = await persisted.json();
  expect(final.status).toBe("disposed");
  expect(final.updated_at).toBe(matter.updated_at);
}
