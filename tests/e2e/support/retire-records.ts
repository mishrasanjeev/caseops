/**
 * Retirement for records a production spec creates, through the product's
 * own endpoints. Production tenants retain every run's records, so a spec
 * leaves only retired residue: a retired IP docket (its scheduled hearings,
 * queued reminders and open work are cancelled with it) or a disposed Matter.
 */
import { expect, type APIRequestContext } from "@playwright/test";

type Docket = { id: string; lifecycle_version: number; matter_id: string | null; status: string };
type Matter = { id: string; status: string; updated_at: string };

export async function retireIpDocket(
  request: APIRequestContext,
  apiOrigin: string,
  headers: Record<string, string>,
  docketId: string,
  reason: string,
): Promise<void> {
  const read = await request.get(`${apiOrigin}/api/ip/dockets/${docketId}`, { headers });
  expect(read.status(), "read the spec's own docket before retiring it").toBe(200);
  const docket = (await read.json()) as Docket;
  expect(docket.id).toBe(docketId);
  if (docket.status === "retired") return;
  const body = {
    expected_lifecycle_version: docket.lifecycle_version,
    to_status: "retired",
    effective_at: new Date().toISOString(),
    reason,
    outcome: "test record retired",
    source: "manual_review",
    evidence_ref: `e2e:${docketId}`,
    successor_docket_id: null,
    acknowledged_exception_codes: [] as string[],
    second_approver_membership_id: null,
    client_report_handling: "retain",
    linked_matter_handling: docket.matter_id ? "reviewed" : "not_linked",
  };
  const preview = await request.post(`${apiOrigin}/api/ip/dockets/${docketId}/lifecycle/preview`, {
    headers, data: body,
  });
  expect(preview.status(), "preview the spec docket's retirement").toBe(200);
  body.acknowledged_exception_codes = ((await preview.json()) as { blocker_codes?: string[] }).blocker_codes ?? [];
  const retired = await request.post(`${apiOrigin}/api/ip/dockets/${docketId}/lifecycle`, { headers, data: body });
  expect(retired.status(), "retire the spec's own docket").toBe(200);
  expect(await retired.json()).toMatchObject({ docket_id: docketId, status: "retired", is_active: false });
}

/** Disposes a Matter the spec created (idempotent: an already disposed Matter is left as is). */
export async function disposeMatter(
  request: APIRequestContext,
  apiOrigin: string,
  headers: Record<string, string>,
  matterId: string,
  reason: string,
): Promise<void> {
  const read = await request.get(`${apiOrigin}/api/matters/${matterId}`, { headers });
  expect(read.status(), "read the spec's own Matter before disposing it").toBe(200);
  const matter = (await read.json()) as Matter;
  expect(matter.id).toBe(matterId);
  if (matter.status === "disposed") return;
  const disposed = await request.patch(`${apiOrigin}/api/matters/${matterId}/lifecycle/status`, {
    headers,
    data: {
      to_status: "disposed",
      expected_from_status: matter.status,
      expected_updated_at: matter.updated_at,
      reason,
    },
  });
  expect(disposed.status(), "dispose the spec's own Matter").toBe(200);
  expect(((await disposed.json()) as Matter).status).toBe("disposed");
}
