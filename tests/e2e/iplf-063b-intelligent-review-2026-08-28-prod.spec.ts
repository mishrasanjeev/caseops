/** IPLF-063B exact-release production acceptance for UJ-18. */

import { expect, test, type APIResponse, type Page } from "@playwright/test";

import { expectStatus } from "./support/iplf058b";

const WEB = (process.env.PROD_BASE_URL ?? "https://caseops.ai").trim();
const API = (process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai").trim();
const SLUG = (process.env.CASEOPS_IP_QA_SLUG ?? "caseops-ip-qa").trim();
const EMAIL = (
  process.env.CASEOPS_IP_QA_EMAIL ?? "ip-qa-bot@caseops.ai"
).trim();

function required(name: string) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

async function authenticate(page: Page) {
  const response = await page.request.post(`${API}/api/auth/login`, {
    data: {
      company_slug: SLUG,
      email: EMAIL,
      password: required("CASEOPS_IP_QA_PASSWORD"),
    },
  });
  await expectStatus(response, 200, "IP QA sign-in");
  const session = await response.json();
  await page.goto(`${WEB}/`);
  await page.evaluate(
    (context) => {
      window.localStorage.setItem(
        "caseops.session.context",
        JSON.stringify(context),
      );
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

async function json(response: APIResponse, status: number, label: string) {
  await expectStatus(response, status, label);
  return response.json();
}

async function waitForReview(
  page: Page,
  reviewId: string,
  headers: Record<string, string>,
  terminal: string[],
) {
  const deadline = Date.now() + 180_000;
  let body: Record<string, unknown> = {};
  while (Date.now() < deadline) {
    const response = await page.request.get(
      `${API}/api/research/reviews/${reviewId}`,
      { headers },
    );
    if (response.status() === 409) {
      const problem = await response.json();
      expect(problem.detail, JSON.stringify(problem)).toBe(
        "Private source access or generation changed. Run a new review.",
      );
      return { state: "private_generation_changed", problem };
    }
    body = await json(response, 200, "poll intelligent review");
    if (terminal.includes(String(body.state))) return body;
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(
    `Review ${reviewId} did not reach ${terminal.join("/")}: ${JSON.stringify(body)}`,
  );
}

async function queueReviewWithOneGenerationRetry(
  page: Page,
  headers: Record<string, string>,
  data: Record<string, unknown>,
  terminal: string[],
  label: string,
) {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const queued = await json(
      await page.request.post(`${API}/api/research/reviews`, { headers, data }),
      202,
      `${label} (attempt ${attempt})`,
    );
    const review = await waitForReview(page, queued.id, headers, terminal);
    if (review.state !== "private_generation_changed") {
      return { queued, review };
    }
    expect(
      attempt,
      "Only one exact generation-change restart is allowed.",
    ).toBe(1);
    console.log(
      `[IPLF-063B] ${label} restarted after the private generation changed.`,
    );
  }
  throw new Error(
    `${label} did not stabilize after one generation-change restart.`,
  );
}

async function currentPrivateTarget(
  page: Page,
  headers: Record<string, string>,
  sourceType: "matter" | "ip_docket",
  query: string,
  expectedLabelPrefix: string,
) {
  const response = await json(
    await page.request.post(`${API}/api/private-retrieval/search`, {
      headers,
      data: { query, source_types: [sourceType], limit: 10 },
    }),
    200,
    `find current ${sourceType} review target`,
  );
  const target = response.items.find(
    (item: { source_type: string; source_id: string; label: string }) =>
      item.source_type === sourceType &&
      item.label.startsWith(expectedLabelPrefix),
  );
  expect(
    target,
    `The exact current ${sourceType} QA projection is required.`,
  ).toBeTruthy();
  return target as { source_id: string };
}

test("IPLF-063B production proves the exact UJ-18 release", async ({
  page,
}) => {
  test.setTimeout(420_000);
  page.setDefaultTimeout(30_000);
  const expectedSha = required("CASEOPS_EXPECTED_RELEASE_SHA");
  const [apiIdentity, webIdentity] = await Promise.all([
    page.request.get(`${API}/api/build`),
    page.request.get(`${WEB}/api/release-identity`),
  ]);
  await expectStatus(apiIdentity, 200, "API release identity");
  await expectStatus(webIdentity, 200, "web release identity");
  expect((await apiIdentity.json()).release_sha).toBe(expectedSha);
  expect((await webIdentity.json()).release_sha).toBe(expectedSha);

  const session = await authenticate(page);
  const headers = { Authorization: `Bearer ${session.access_token}` };
  const run = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const search = await json(
    await page.request.post(`${API}/api/authorities/search`, {
      headers,
      data: {
        query: "IPLF 063B production QA",
        mode: "keyword",
        language: "any",
      },
    }),
    200,
    "find bounded production review fixtures",
  );
  const fixtures = new Map(
    search.results.map(
      (item: { title: string; authority_document_id: string }) => [
        item.title,
        item.authority_document_id,
      ],
    ),
  );
  const supportingId = fixtures.get(
    "IPLF 063B production QA supporting authority",
  );
  const contraryId = fixtures.get("IPLF 063B production QA contrary authority");
  const inaccessibleId = fixtures.get(
    "IPLF 063B production QA inaccessible authority",
  );
  expect(supportingId, "production supporting fixture").toBeTruthy();
  expect(contraryId, "production contrary fixture").toBeTruthy();
  expect(inaccessibleId, "production inaccessible fixture").toBeTruthy();
  const releaseKey = expectedSha.slice(0, 12).toLowerCase();
  const matterCodePrefix = `IPLF-066B-${releaseKey.toUpperCase()}`;
  const docketTitle = `IPLF-063B exact-release review ${releaseKey}`;

  // IPLF-066B makes private source capture fail closed. A target created after
  // the release bootstrap is intentionally not current until the bounded
  // maintenance path materializes a new verified generation. UJ-18 acceptance
  // therefore selects existing synthetic projections from the public,
  // authorization-filtered private search surface instead of racing that
  // independent maintenance boundary.
  const matterTarget = await currentPrivateTarget(
    page,
    headers,
    "matter",
    matterCodePrefix,
    `${matterCodePrefix}`,
  );
  const docketTarget = await currentPrivateTarget(
    page,
    headers,
    "ip_docket",
    docketTitle,
    docketTitle,
  );
  const coreRecords = await json(
    await page.request.get(
      `${API}/api/ip/dockets/${docketTarget.source_id}/core-records`,
      {
        headers,
      },
    ),
    200,
    "load exact-release intelligent-review opposition",
  );
  const proceedings = coreRecords.proceedings.filter(
    (item: {
      application_id: string | null;
      proceeding_kind: string;
      side: string;
      stage: string;
      origin_kind: string;
      source_pending_identifier_allocation: boolean;
    }) =>
      item.application_id === null &&
      item.proceeding_kind === "opposition" &&
      item.side === "opponent" &&
      item.stage === "draft" &&
      item.origin_kind === "registry_event" &&
      item.source_pending_identifier_allocation,
  );
  expect(
    proceedings,
    "one exact-release intelligent-review opposition",
  ).toHaveLength(1);
  const proceeding = proceedings[0];
  const report = await json(
    await page.request.post(`${API}/api/authorities/research-reports`, {
      headers,
      data: {
        name: `IPLF 063B production accessible report ${run}`,
        query: "prior use and deceptive similarity",
        mode: "keyword",
        result_ids: [supportingId, contraryId],
        criteria: { synthetic_qa: true },
      },
    }),
    201,
    "create production accessible report",
  );
  const blockedReport = await json(
    await page.request.post(`${API}/api/authorities/research-reports`, {
      headers,
      data: {
        name: `IPLF 063B production inaccessible report ${run}`,
        query: "inaccessible source abstention",
        mode: "keyword",
        result_ids: [inaccessibleId],
        criteria: { synthetic_qa: true },
      },
    }),
    201,
    "create production inaccessible report",
  );

  const { queued, review: ready } = await queueReviewWithOneGenerationRetry(
    page,
    headers,
    {
      matter_id: matterTarget.source_id,
      source_research_report_id: report.id,
      issue: `Does proved prior use support opposition ${run}?`,
      facts: [
        { label: "First use", value: "2018", source_ref: "client instruction" },
        { label: "First use", value: "2019", source_ref: "registry form" },
      ],
      document_refs: ["client instruction v1", "registry form v2"],
      included_authority_ids: [supportingId, contraryId],
    },
    ["ready", "abstained", "failed"],
    "queue production intelligent review",
  );
  expect(ready.state, JSON.stringify(ready)).toBe("ready");
  expect(ready.supporting_authorities).toHaveLength(1);
  expect(ready.contrary_authorities).toHaveLength(1);
  expect(ready.stale_warning).toBeTruthy();
  expect(ready.unresolved_contradictions.join(" ")).toContain("First use");
  expect(ready.supporting_authorities[0].source_url).toMatch(/^https:\/\//);
  expect(ready.contrary_authorities[0].source_url).toMatch(/^https:\/\//);
  expect(JSON.stringify(ready)).not.toMatch(
    /\b\d{1,3}%\b|guaranteed strategy|judge favour|judge favor/i,
  );

  const supportingAuthorityId =
    ready.supporting_authorities[0].authority_document_id;
  const contraryAuthorityId =
    ready.contrary_authorities[0].authority_document_id;
  const incomplete = await json(
    await page.request.patch(
      `${API}/api/research/reviews/${queued.id}/authorities`,
      {
        headers,
        data: {
          included_authority_ids: [supportingAuthorityId],
          lawyer_notes:
            "Contrary source temporarily excluded for completeness proof.",
        },
      },
    ),
    200,
    "remove a cited contrary authority",
  );
  expect(incomplete.completeness.complete).toBe(false);
  expect(incomplete.completeness.reasons.join(" ")).toContain(
    "A generated contrary authority was removed",
  );
  const restored = await json(
    await page.request.patch(
      `${API}/api/research/reviews/${queued.id}/authorities`,
      {
        headers,
        data: {
          included_authority_ids: [supportingAuthorityId, contraryAuthorityId],
          lawyer_notes: "Both sides verified against the frozen source record.",
        },
      },
    ),
    200,
    "restore complete source selection",
  );
  expect(restored.completeness.complete).toBe(true);
  const finalized = await json(
    await page.request.post(
      `${API}/api/research/reviews/${queued.id}/finalize`,
      {
        headers,
        data: { lawyer_notes: "Approved for the existing Draft lifecycle." },
      },
    ),
    200,
    "finalize production review",
  );
  expect(finalized.state).toBe("finalized");
  const published = await json(
    await page.request.post(
      `${API}/api/research/reviews/${queued.id}/publish`,
      {
        headers,
        data: { title: `Production intelligent review ${run}` },
      },
    ),
    200,
    "publish production review to Drafts",
  );
  expect(published.review.state).toBe("published");
  expect(published.review.published_draft_id).toBe(published.draft_id);

  const { queued: ipQueued, review: ipReady } =
    await queueReviewWithOneGenerationRetry(
      page,
      headers,
      {
        ip_docket_id: docketTarget.source_id,
        ip_proceeding_id: proceeding.id,
        source_research_report_id: report.id,
        issue: `Does proved prior use support IP opposition ${run}?`,
        facts: [],
        document_refs: [],
        included_authority_ids: [supportingId, contraryId],
      },
      ["ready", "abstained", "failed"],
      "queue production IP intelligent review",
    );
  expect(ipReady.state, JSON.stringify(ipReady)).toBe("ready");
  const ipFinalized = await json(
    await page.request.post(
      `${API}/api/research/reviews/${ipQueued.id}/finalize`,
      {
        headers,
        data: {
          lawyer_notes: "Approved for the exact opposition Draft handoff.",
        },
      },
    ),
    200,
    "finalize production IP intelligent review",
  );
  expect(ipFinalized.state).toBe("finalized");
  const ipPublished = await json(
    await page.request.post(
      `${API}/api/research/reviews/${ipQueued.id}/publish`,
      {
        headers,
        data: { title: `Production IP intelligent review ${run}` },
      },
    ),
    200,
    "publish production IP intelligent review",
  );
  expect(ipPublished.review.ip_docket_id).toBe(docketTarget.source_id);
  expect(ipPublished.review.ip_proceeding_id).toBe(proceeding.id);
  await page.goto(
    `${WEB}/app/ip?docket=${docketTarget.source_id}&view=proceedings&proceeding=${proceeding.id}&draft=${ipPublished.draft_id}`,
  );
  await expect(page.getByRole("tab", { name: "Proceedings" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(
    page.getByLabel("Opposition proceeding", { exact: true }),
  ).toHaveValue(proceeding.id);
  await expect(page.getByTestId("ip-pleading-workspace")).toHaveAttribute(
    "aria-busy",
    "false",
    { timeout: 60_000 },
  );
  await expect(page.getByLabel("Pleading draft", { exact: true })).toHaveValue(
    ipPublished.draft_id,
  );
  await expect(page.getByLabel("Pleading body", { exact: true })).toHaveValue(
    /source-bounded decision support/i,
  );

  const { review: abstained } = await queueReviewWithOneGenerationRetry(
    page,
    headers,
    {
      matter_id: matterTarget.source_id,
      source_research_report_id: blockedReport.id,
      issue: `Inaccessible-only review ${run}`,
      facts: [],
      document_refs: [],
      included_authority_ids: [inaccessibleId],
    },
    ["abstained", "failed"],
    "queue inaccessible-only review",
  );
  expect(abstained.state).toBe("abstained");
  expect(abstained.error_code).toBe("insufficient_accessible_sources");

  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(
    `${WEB}/app/research/reviews?review=${encodeURIComponent(ipQueued.id)}`,
  );
  const detail = page.getByTestId("intelligent-review-detail");
  await expect(
    detail.getByRole("heading", {
      name: `Does proved prior use support IP opposition ${run}?`,
    }),
  ).toBeVisible();
  await expect(
    detail.getByText("Supporting and contrary authorities"),
  ).toBeVisible();
  await expect(detail.getByText(/not exhaustive legal research/)).toBeVisible();
  await expect(detail.getByRole("link", { name: /Open Draft/ })).toBeVisible();
  for (const name of [
    "Frozen research report",
    "Matter target",
    "Issue for review",
  ]) {
    await expect(page.getByLabel(name)).toBeVisible();
  }
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth + 1,
    ),
  ).toBe(false);
  await page.goto(`${WEB}/guide`);
  await expect(
    page.getByText("Intelligent-review safety boundary"),
  ).toBeVisible();
  await page.goto(`${WEB}/law-firms`);
  await expect(
    page.getByRole("heading", { name: "Source-bounded intelligent review" }),
  ).toBeVisible();
});
