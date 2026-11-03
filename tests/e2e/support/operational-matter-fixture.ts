/** Read-only, bounded fixture admission for the BUG-015 operational request. */
type Matter = {
  id: string;
  company_id: string;
  status: "intake" | "active" | "on_hold" | "disposed";
  is_active: boolean;
};

type MatterPage = {
  company_id: string;
  matters: Matter[];
  next_cursor: string | null;
};

type FixtureRequest = {
  get: (
    url: string,
    options: { headers: Record<string, string>; timeout: number },
  ) => Promise<{ status: () => number; json: () => Promise<unknown> }>;
};

type SetupFailure =
  | "PREFERRED_ID"
  | "DEADLINE"
  | "TRANSPORT"
  | "AUTHORIZATION"
  | "HTTP_RESPONSE"
  | "JSON_RESPONSE"
  | "DTO_RESPONSE"
  | "READBACK_IDENTITY"
  | "CURSOR_CYCLE"
  | "PAGE_LIMIT"
  | "CANDIDATE_LIMIT"
  | "NO_OPERATIONAL_MATTER";

const LIST_PAGE_SIZE = 50;
const MAX_LIST_PAGES = 3;
const MAX_REVALIDATIONS = 6;
const READ_TIMEOUT_MS = 5_000;
const SETUP_TIMEOUT_MS = 20_000;

function fail(code: SetupFailure): never {
  // Fixed vocabulary only: do not reflect a response, id, cookie or transport error.
  throw new Error(
    `BUG-015 fixture setup failed (${code}); paid-provider boundary is unverified.`,
  );
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parsePage(value: unknown, companyId: string | null): MatterPage {
  if (
    !record(value)
    || typeof value.company_id !== "string"
    || value.company_id.length === 0
    || (companyId !== null && value.company_id !== companyId)
    || !Array.isArray(value.matters)
    || value.matters.length > LIST_PAGE_SIZE
    || !Object.hasOwn(value, "next_cursor")
    || !(value.next_cursor === null || typeof value.next_cursor === "string")
  ) fail("DTO_RESPONSE");

  const matters: Matter[] = [];
  for (const row of value.matters) {
    if (
      !record(row)
      || typeof row.id !== "string"
      || row.id.length === 0
      || row.id.length > 36 // MatterListFilters.id's supported input domain.
      || row.company_id !== value.company_id
      || typeof row.status !== "string"
      || !["intake", "active", "on_hold", "disposed"].includes(row.status)
      || typeof row.is_active !== "boolean"
    ) fail("DTO_RESPONSE");
    matters.push({
      id: row.id,
      company_id: row.company_id as string,
      status: row.status as Matter["status"],
      is_active: row.is_active,
    });
  }
  return {
    company_id: value.company_id,
    matters,
    next_cursor: value.next_cursor as string | null,
  };
}

function operational(matter: Matter): boolean {
  // Mirrors matter_operational_guard: intake and on_hold also remain operational.
  return matter.is_active && matter.status !== "disposed";
}

export async function selectOperationalMatterForRecommendations(
  request: FixtureRequest,
  apiBaseUrl: string,
  headers: Record<string, string>,
  now: () => number = () => performance.now(),
  preferredId?: string,
): Promise<string> {
  // Match MatterListFilters.id before any HTTP admission; never reflect the hint.
  if (preferredId !== undefined && (
    typeof preferredId !== "string" || preferredId.length === 0 || preferredId.length > 36
  )) fail("PREFERRED_ID");
  const deadline = now() + SETUP_TIMEOUT_MS;
  const readHeaders = {
    ...headers,
    // Each actual read owns isolation, independently of Playwright configuration.
    "X-CaseOps-Automated-Test": "no-paid-providers",
  };
  const checkTime = () => {
    if (now() >= deadline) fail("DEADLINE");
  };
  let companyId: string | null = null;

  const read = async (query: URLSearchParams): Promise<MatterPage> => {
    const remaining = deadline - now();
    if (remaining <= 0) fail("DEADLINE");
    let response: Awaited<ReturnType<FixtureRequest["get"]>>;
    try {
      response = await request.get(`${apiBaseUrl}/api/matters/?${query}`, {
        headers: { ...readHeaders },
        timeout: Math.min(READ_TIMEOUT_MS, remaining),
      });
    } catch {
      fail("TRANSPORT");
    }
    checkTime();
    const status = response.status();
    if (status === 401 || status === 403) fail("AUTHORIZATION");
    if (status !== 200) fail("HTTP_RESPONSE");
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      fail("JSON_RESPONSE");
    }
    checkTime();
    return parsePage(body, companyId);
  };

  const candidates = new Set<string>();
  const revalidate = async (id: string): Promise<string | null> => {
    if (candidates.size >= MAX_REVALIDATIONS) fail("CANDIDATE_LIMIT");
    candidates.add(id);
    // The normal id list filter retains current tenant + ethical-wall visibility.
    // A hidden hint is an empty list, never a reason to probe a denied detail route.
    const current = await read(new URLSearchParams({ id, limit: "1" }));
    companyId = current.company_id;
    if (
      current.matters.length > 1
      || (current.matters.length === 1 && current.matters[0].id !== id)
      || current.next_cursor !== null
    ) fail("READBACK_IDENTITY");
    if (current.matters.length === 1 && operational(current.matters[0])) {
      checkTime();
      return current.matters[0].id;
    }
    return null;
  };

  if (preferredId !== undefined) {
    const preferred = await revalidate(preferredId);
    if (preferred !== null) return preferred;
  }

  let listedPages = 0;
  // Preserve main's one active-filtered shortlist when a preferred hint is stale.
  // It shares the original three-page/six-readback budget with the fallback.
  const scopes: Array<"active" | null> = preferredId === undefined ? [null] : ["active", null];
  for (const status of scopes) {
    let cursor: string | null = null;
    const cursors = new Set<string>();
    while (listedPages < MAX_LIST_PAGES) {
      const query = new URLSearchParams({ limit: String(LIST_PAGE_SIZE) });
      if (status !== null) query.set("status", status);
      if (cursor !== null) query.set("cursor", cursor);
      const listed = await read(query);
      listedPages += 1;
      companyId = listed.company_id;
      for (const matter of listed.matters) {
        if (!operational(matter) || candidates.has(matter.id)) continue;
        const selected = await revalidate(matter.id);
        if (selected !== null) return selected;
      }
      // This is the same single filtered lookup as main. Never carry its opaque
      // cursor into the unfiltered scope, which can admit intake/on_hold too.
      if (status === "active") break;
      if (listed.next_cursor === null) fail("NO_OPERATIONAL_MATTER");
      if (cursors.has(listed.next_cursor)) fail("CURSOR_CYCLE");
      cursors.add(listed.next_cursor);
      cursor = listed.next_cursor;
    }
  }
  fail("PAGE_LIMIT");
}
