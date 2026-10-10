export type SummaryIdentity = {
  company_id: string; actor_id: string; matter_id: string;
  scenario: "positive" | "marked" | "persistent_qa";
};
export type SummarySeed = SummaryIdentity & { bookmark_id: string; update_id: string };
export type SummaryBatchRow = {
  identity: SummaryIdentity | SummarySeed; seed?: SummarySeed; inspection: unknown;
};

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function reconcileSummaryBatch(
  expected: (SummaryIdentity | SummarySeed)[], response: unknown,
): SummaryBatchRow[] {
  if (expected.length < 1 || expected.length > 3 || !object(response)
    || response.ok !== true || response.failure !== null || !Array.isArray(response.items)
    || response.items.length !== expected.length) {
    throw new Error("Summary batch is incomplete or outside its identity bound.");
  }
  const rows = response.items;
  const identityKeys = Object.keys(expected[0]).sort();
  const key = (identity: Record<string, unknown>) => JSON.stringify(identityKeys.map(name => identity[name]));
  const expectedKeys = expected.map(identity => key(identity));
  if (new Set(expectedKeys).size !== expected.length) throw new Error("Duplicate expected summary identity.");
  const received = new Map<string, SummaryBatchRow>();
  for (const row of rows) {
    if (!object(row) || !object(row.identity) || !object(row.inspection)
      || JSON.stringify(Object.keys(row.identity).sort()) !== JSON.stringify(identityKeys)) {
      throw new Error("Summary batch returned a malformed identity or raw inspection.");
    }
    const id = key(row.identity);
    if (!expectedKeys.includes(id) || received.has(id)) {
      throw new Error("Summary batch returned an unknown or duplicate identity.");
    }
    if (identityKeys.includes("update_id")) {
      if (row.seed !== undefined) throw new Error("Inspection batch unexpectedly returned a seed.");
    } else {
      const seed = row.seed, identity = row.identity;
      if (!object(seed)
        || JSON.stringify(Object.keys(seed).sort()) !== JSON.stringify([...identityKeys, "bookmark_id", "update_id"].sort())
        || identityKeys.some(name => seed[name] !== identity[name])
        || [seed.bookmark_id, seed.update_id].some(value => typeof value !== "string" || !value.length || value.length > 36)) {
        throw new Error("Seed batch returned a different fixture identity.");
      }
    }
    received.set(id, row as SummaryBatchRow);
  }
  if (!identityKeys.includes("update_id")) {
    for (const field of ["bookmark_id", "update_id"] as const) {
      if (new Set([...received.values()].map(row => row.seed![field])).size !== expected.length) {
        throw new Error("Seed batch returned duplicate child identities.");
      }
    }
  }
  return expectedKeys.map(id => received.get(id)!);
}

export type SummaryCleanupStep = { name: string; run: () => unknown | Promise<unknown> };

type WorkerIdentity = {
  Id: string; Image: string; State: { Running: boolean };
  Config: { Labels: Record<string, string> };
};

export function restoreSummaryWorker(
  original: WorkerIdentity, project: string,
  inspect: (id: string) => WorkerIdentity,
  setRunning: (id: string, running: boolean) => void,
): void {
  const current = inspect(original.Id);
  if (current.Id !== original.Id || current.Image !== original.Image
    || current.Config.Labels["com.docker.compose.project"] !== project
    || current.Config.Labels["com.docker.compose.service"] !== "worker"
    || current.Config.Labels["com.docker.compose.oneoff"] !== "False") {
    throw new Error("Refusing to restore a worker outside the original owned container identity.");
  }
  if (current.State.Running !== original.State.Running) setRunning(original.Id, original.State.Running);
}

export async function runSummaryCleanup(
  steps: SummaryCleanupStep[],
  record: (phase: string, detail: unknown) => void,
  originalErrors: unknown[] = [],
): Promise<void> {
  const failures: unknown[] = [];
  for (const step of steps) {
    let detail: unknown;
    try {
      detail = { step: step.name, outcome: "passed", result: await step.run() };
    } catch (error) {
      failures.push(error);
      detail = { step: step.name, outcome: "failed", error: String(error) };
    }
    try { record("cleanup_step", detail); }
    catch (error) { failures.push(error); }
  }
  if (failures.length) {
    const errors = [...originalErrors, ...failures];
    throw new AggregateError(errors, "Summary cleanup failed; all owned cleanup steps were attempted.\n"
      + errors.map(error => String(error)).join("\n"),
      { cause: originalErrors.length ? originalErrors[0] : failures[0] });
  }
  if (originalErrors.length) throw originalErrors[0];
}
