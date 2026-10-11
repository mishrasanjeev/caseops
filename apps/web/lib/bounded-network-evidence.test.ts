import { describe, expect, it } from "vitest";
import { BoundedNetworkEvidence } from "../../../tests/e2e/support/bounded-network-evidence";

describe("bounded failure evidence prioritizes writes", () => {
  it("retains the last failed notice mutation after a navigation flood", () => {
    const evidence = new BoundedNetworkEvidence<number>();
    for (let index = 0; index < 600; index++) evidence.start(index, { route: "web/app-navigation", method: "GET", startedAt: "now" });
    evidence.start(601, { route: "matter/attachment", method: "POST", startedAt: "now" });
    expect(evidence.pending.size).toBe(1);
    evidence.add({ route: "matter/attachment", method: "POST", status: 503, outcome: "response_completed" });
    expect(evidence.snapshot()).toEqual({ omitted: 600, records: [{ route: "matter/attachment", method: "POST", status: 503, outcome: "response_completed" }] });
  });
  it("bounds raw requests and completed records while keeping mutations", () => {
    const evidence = new BoundedNetworkEvidence<number>();
    for (let index = 0; index < 200; index++) evidence.start(index, { route: "auth/session", method: "GET", startedAt: "now" });
    evidence.start(201, { route: "matter/attachment", method: "POST", startedAt: "now" });
    expect(evidence.pending.size).toBe(128);
    expect(evidence.pending.has(201)).toBe(true);
    for (let index = 0; index < 100; index++) evidence.add({ method: "GET", status: 200, outcome: "response_completed" });
    evidence.add({ route: "matter/attachment", method: "POST", status: 503, outcome: "response_completed" });
    for (let index = 0; index < 100; index++) evidence.add({ method: "GET", status: 200, outcome: "response_completed" });
    expect(evidence.records).toHaveLength(64);
    expect(evidence.records.some((row) => row.status === 503)).toBe(true);
    expect(evidence.omitted).toBe(73 + 137);
  });
  it("keeps newest failures when the failure-only budget is exhausted and snapshots are independent", () => {
    const evidence = new BoundedNetworkEvidence<number>();
    for (let index = 0; index < 100; index++) evidence.add({ method: "POST", status: 503, ordinal: index });
    expect(evidence.records).toHaveLength(64);
    expect(evidence.records[63].ordinal).toBe(99);
    expect(evidence.omitted).toBe(36);
    evidence.snapshot().records[0].status = 200;
    expect(evidence.records[0].status).toBe(503);
  });
  it("bounds deferred responses without body promises and retains a late failed write", () => {
    const evidence = new BoundedNetworkEvidence<number>();
    for (let index = 0; index < 1000; index++) {
      evidence.start(index, { route: "auth/session", method: "GET", startedAt: "now" });
      evidence.received(index, 200, null);
    }
    expect(evidence.pending.size).toBe(128);
    evidence.start(1001, { route: "matter/attachment", method: "POST", startedAt: "now" });
    evidence.received(1001, 503, "a".repeat(32));
    evidence.finish(1001, "later");
    expect(evidence.snapshot().records[0]).toEqual({
      route: "matter/attachment", method: "POST", startedAt: "now", finishedAt: "later",
      outcome: "response_completed", status: 503, requestId: "a".repeat(32), problemType: null,
    });
    evidence.retainPending();
    expect(evidence.pending.size).toBe(0);
    expect(evidence.records).toHaveLength(64);
    expect(evidence.records.some((entry) => entry.status === 503)).toBe(true);
    expect(evidence.records.every((entry) => !("response" in entry))).toBe(true);
  });
  it("retains transport failure without response data or inspecting a body", () => {
    const evidence = new BoundedNetworkEvidence<number>();
    evidence.start(1, { route: "matter/attachment", method: "POST", startedAt: "now" });
    evidence.received(1, 503, "a".repeat(32));
    evidence.fail(1, "later", "connection_reset");
    expect(evidence.snapshot().records).toEqual([{
      route: "matter/attachment", method: "POST", startedAt: "now", finishedAt: "later",
      outcome: "transport_failed", failureCode: "connection_reset",
    }]);
    expect(evidence.pending.size).toBe(0);
  });
});
