import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, type APIRequestContext } from "@playwright/test";

import { e2eEnv, repoRoot } from "./env";
import { expectStatus } from "./iplf058b";

export function isLoopback(url: string): boolean {
  return ["127.0.0.1", "localhost", "[::1]"].includes(new URL(url).hostname);
}

export function runLoopbackSavedManifestFixture(
  api: string,
  web: string,
  operation: "seed" | "rebuild",
  values: Record<string, string>,
): void {
  if (!isLoopback(api) || !isLoopback(web)) {
    throw new Error("Saved-manifest Python fixtures are strictly loopback-only.");
  }
  const database = process.env.CASEOPS_E2E_DATABASE_URL?.trim() || e2eEnv.CASEOPS_DATABASE_URL;
  if (!database.startsWith("sqlite+") && !isLoopback(database.replace(/^postgresql\+psycopg:/, "http:"))) {
    throw new Error("Saved-manifest fixture refuses a non-loopback database.");
  }
  const python = process.env.CASEOPS_E2E_PYTHON?.trim() || path.join(
    repoRoot, "apps", "api", ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
  );
  const script = operation === "seed" ? [
    "import os",
    "from caseops_api.db.session import get_session_factory",
    "from caseops_api.scripts.bootstrap_ip_production_qa import ensure_ip_production_qa,ensure_ip_production_qa_saved_manifest_fixture",
    "with get_session_factory()() as s:",
    " qa=ensure_ip_production_qa(s,company_name='CaseOps IP QA LLP',company_slug=os.environ['QA_SLUG'],owner_full_name='CaseOps IP QA Bot',owner_email=os.environ['QA_EMAIL'],owner_password=os.environ['QA_PASSWORD'])",
    " ensure_ip_production_qa_saved_manifest_fixture(s,company_id=qa.company_id,membership_id=qa.membership_id,release_sha=os.environ['QA_SHA'],member_password=os.environ['QA_PASSWORD'])",
  ].join("\n") : [
    "import os",
    "from caseops_api.db.session import get_session_factory",
    "from caseops_api.services.private_retrieval_jobs import rebuild_private_index",
    "with get_session_factory()() as s:",
    " rebuild_private_index(s,company_id=os.environ['QA_COMPANY_ID'],activate=True)",
    " s.commit()",
  ].join("\n");
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot, encoding: "utf8", timeout: 180_000,
    env: {
      ...process.env,
      ...e2eEnv,
      CASEOPS_ENV: process.env.CASEOPS_ENV || "e2e",
      CASEOPS_DATABASE_URL: database,
      CASEOPS_LLM_PROVIDER: "mock",
      CASEOPS_LLM_MODEL: "caseops-mock-1",
      ...values,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean).join(path.delimiter),
    },
  });
  expect(result.error, "loopback release fixture runtime").toBeUndefined();
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
}

export type FrozenCase = {
  matter_id: string;
  attachment_id: string;
  source_version: string;
  draft_id: string;
  version_id: string;
  body_sha256: string;
  manifest_sha256: string;
};

export type SavedManifestFixture = {
  schema: string;
  release_sha: string;
  anchor_id: string;
  matter_code: string;
  membership_id: string;
  member_email: string;
  captured_generation_id: string;
  benign_generation_id: string;
  retired_at: string;
  owner_membership_id: string;
  post_event_generation_id?: string;
  post_event_activated_at?: string;
  later_event_audit_ids?: Record<"access" | "tombstone", string[]>;
  cases: Record<"access" | "tombstone" | "control", FrozenCase>;
};

export function frozenQaBody(fixture: SavedManifestFixture, name: "access" | "tombstone" | "control"): string {
  return `Synthetic frozen Draft QA evidence: ${fixture.matter_code} ${name}. Not a legal opinion.`;
}

export async function settledGeneration(
  owner: APIRequestContext, api: string, previous?: string,
): Promise<string> {
  if (!isLoopback(api)) throw new Error("Production QA must never wait on paused maintenance cadence.");
  let active = "";
  await expect.poll(async () => {
    const response = await owner.get(`${api}/api/private-retrieval/integrity`);
    await expectStatus(response, 200, "read release maintenance generation");
    const integrity = await response.json();
    active = integrity.active_generation_id;
    // AI policy may be disabled: this proof reads frozen output and does not
    // enable retrieval or invoke a model. Inspect the actual generation fence.
    return Boolean(active && active !== previous && integrity.generation_manifest_matches &&
      integrity.pending_event_count === 0 && integrity.failed_event_count === 0 &&
      integrity.stale_source_count === 0 && integrity.orphan_scope_count === 0 &&
      integrity.unsafe_tombstone_count === 0);
  }, {
    timeout: 30_000, intervals: [1_000],
    message: "The explicitly invoked local rebuild must settle before certifying retained output",
  }).toBe(true);
  return active;
}

export async function assertLaterAudit(
  owner: APIRequestContext, api: string, fixture: SavedManifestFixture,
  name: "access" | "tombstone",
): Promise<void> {
  const response = await owner.get(`${api}/api/matters/${fixture.cases[name].matter_id}/audit-events`, {
    params: { limit: 100, offset: 0 },
  });
  await expectStatus(response, 200, "read retained later-event evidence");
  const audit = await response.json();
  expect(audit.total, "bounded fixture audit inventory").toBeLessThanOrEqual(100);
  const actions = name === "access"
    ? ["matter.ethical_wall_added", "matter.ethical_wall_removed"]
    : ["matter.lifecycle.disposed", "matter.lifecycle.reopened"];
  for (const [index, action] of actions.entries()) {
    expect(audit.events.some((event: { id: string; actor_membership_id: string; action: string; created_at: string; result: string }) =>
      event.action === action && event.result === "success" &&
      event.actor_membership_id === fixture.owner_membership_id &&
      Date.parse(event.created_at) >= Date.parse(fixture.retired_at) &&
      (!fixture.later_event_audit_ids || event.id === fixture.later_event_audit_ids[name][index]) &&
      (!fixture.post_event_activated_at || Date.parse(event.created_at) <= Date.parse(fixture.post_event_activated_at))),
    `${action} must be retained and later than benign retirement`).toBe(true);
  }
}
