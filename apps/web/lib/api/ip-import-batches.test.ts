import { beforeEach, describe, expect, it, vi } from "vitest";

const { call } = vi.hoisted(() => ({ call: vi.fn() }));
vi.mock("./client", () => ({
  apiRequest: call, apiBlobRequest: vi.fn(), fetchWithTimeout: vi.fn(), getCsrfHeaders: vi.fn(),
}));
import { commitIpPortfolioImport, resumeIpPortfolioImport, type IpImportPreview } from "./endpoints";

function result(status: "staged" | "committed", version: number): IpImportPreview & { replayed: boolean } {
  return {
    job: { id: "owned-job", domain: "ip_trademark", filename: "owned.csv", source_sha256: "a".repeat(64),
      status, total_rows: 2, valid_rows: 2, invalid_rows: 0, committed_rows: status === "staged" ? 1 : 2,
      failed_rows: 0, preview_token: null, preview_expires_at: null, committed_at: null,
      creator_label_snapshot: "Isolated owner", version, created_at: "2026-10-13T00:00:00Z",
      recovery_available: status === "staged", commit_batch_size: 50 },
    rows: [1, 2].map(number => ({ id: `row-${number}`, row_number: number, validation_status: "valid",
      errors: [], commit_status: status === "staged" && number === 2 ? "pending" : "committed",
      commit_error_code: null, created_docket_id: status === "staged" && number === 2 ? null : `docket-${number}`,
      normalized: {}, duplicate_candidates: [], reconciliation_decision: null, reconciled_target_docket_id: null })),
    preview_expired: false, replayed: false,
  };
}

describe("acknowledged IP import batches", () => {
  beforeEach(() => call.mockReset());

  it("continues successful batches with server version and publishes truthful progress", async () => {
    const progress = vi.fn();
    call.mockResolvedValueOnce(result("staged", 2)).mockResolvedValueOnce(result("committed", 3));
    const saved = await commitIpPortfolioImport({ jobId: "owned-job", previewToken: "reviewed",
      idempotencyKey: "original-key", onProgress: progress });
    expect(saved.job.status).toBe("committed");
    expect(progress.mock.calls.map(args => args[0].job.status)).toEqual(["staged", "committed"]);
    expect(call).toHaveBeenCalledTimes(2);
    expect(call.mock.calls[1]).toEqual(["/api/ip/imports/owned-job/resume", {
      method: "POST", body: { expected_job_version: 2, preview_token: null },
    }]);
  });

  it("stops on a failed mutation without transport retry or false completion", async () => {
    const progress = vi.fn();
    call.mockResolvedValueOnce(result("staged", 2)).mockRejectedValueOnce(new Error("response lost"));
    await expect(resumeIpPortfolioImport({ jobId: "owned-job", expectedJobVersion: 1,
      previewToken: null, onProgress: progress })).rejects.toThrow("response lost");
    expect(call).toHaveBeenCalledTimes(2);
    expect(progress).toHaveBeenCalledTimes(1);
    expect(progress.mock.calls[0][0].job.status).toBe("staged");
  });

  it("rejects stalled, foreign and falsely terminal progress without another mutation", async () => {
    for (const kind of ["stalled", "foreign", "pending-terminal"] as const) {
      call.mockReset();
      const progress = vi.fn();
      const next = kind === "stalled" ? result("staged", 2) : result("committed", 3);
      if (kind === "foreign") next.job.id = "another-job";
      if (kind === "pending-terminal") next.rows[1].commit_status = "pending";
      call.mockResolvedValueOnce(result("staged", 2)).mockResolvedValueOnce(next);
      await expect(commitIpPortfolioImport({ jobId: "owned-job", previewToken: "reviewed",
        idempotencyKey: "original-key", onProgress: progress })).rejects.toThrow(/progress|identity|pending/i);
      expect(call).toHaveBeenCalledTimes(2);
      expect(progress.mock.calls.map(args => args[0].job.status)).toEqual(["staged"]);
    }
  });

  it("rejects a missing server batch bound before issuing a resume", async () => {
    const missing = result("staged", 2);
    delete missing.job.commit_batch_size;
    call.mockResolvedValueOnce(missing);
    await expect(commitIpPortfolioImport({ jobId: "owned-job", previewToken: "reviewed",
      idempotencyKey: "original-key" })).rejects.toThrow("server batch limit");
    expect(call).toHaveBeenCalledTimes(1);
  });
});
