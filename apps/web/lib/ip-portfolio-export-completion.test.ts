// @vitest-environment node

import { describe, expect, it, vi } from "vitest";
import { PORTFOLIO_EXPORT_COMPLETION_MS, PORTFOLIO_EXPORT_MAX_READS,
  type PortfolioExportCompletion, waitForPortfolioExport } from "../../../tests/e2e/support/ip-portfolio-export-completion";

const complete = { id: "job", status: "completed", download_ready: true, row_count: 51 };
const running = { ...complete, status: "running", download_ready: false, row_count: null };
function fixture() {
  let elapsed = 0;
  const sleep = vi.fn(async (milliseconds: number) => { elapsed += milliseconds; });
  return { timing: { now: () => elapsed, sleep }, advance: (value: number) => { elapsed = value; } };
}

describe("bounded portfolio export completion acceptance", () => {
  it("retains the accepted fifteen-second operation budget and a finite read bound", () => {
    expect(PORTFOLIO_EXPORT_COMPLETION_MS).toBe(15_000);
    expect(PORTFOLIO_EXPORT_MAX_READS).toBe(16);
  });
  it("accepts the observed 10.49-second completion without another enqueue", async () => {
    const f = fixture();
    const read = vi.fn(async (_timeout: number) => {
      if (f.timing.now() < 10_000) return running;
      f.advance(10_490);
      return complete;
    });
    expect(await waitForPortfolioExport("job", read, f.timing)).toEqual(complete);
    expect(read).toHaveBeenCalledTimes(11);
    expect(read.mock.calls.every(([timeout]) => timeout > 0 && timeout <= 5_000)).toBe(true);
  });
  it("rejects completion after the same fifteen-second deadline", async () => {
    const f = fixture();
    const read = vi.fn(async () => { f.advance(15_001); return complete; });
    await expect(waitForPortfolioExport("job", read, f.timing)).rejects.toThrow("bounded completion budget");
    expect(read).toHaveBeenCalledTimes(1);
  });
  it("bounds never-completing jobs without extending the deadline", async () => {
    const f = fixture();
    const read = vi.fn(async (_timeout: number) => running);
    await expect(waitForPortfolioExport("job", read, f.timing)).rejects.toThrow("bounded completion budget");
    expect(f.timing.now()).toBe(15_000);
    expect(read.mock.calls.length).toBeLessThanOrEqual(16);
    expect(read.mock.calls.at(-1)?.[0]).toBe(1_000);
  });
  it("also bounds reads when an injected clock fails to advance", async () => {
    const read = vi.fn(async () => running);
    await expect(waitForPortfolioExport("job", read, { now: () => 0, sleep: async () => {} }))
      .rejects.toThrow("bounded completion budget");
    expect(read).toHaveBeenCalledTimes(16);
  });
  it.each([
    { name: "failed job", record: { ...running, status: "failed" }, message: "Portfolio export failed." },
    { name: "wrong identity", record: { ...complete, id: "another" }, message: "another job" },
    { name: "unknown state", record: { ...running, status: "unknown" }, message: "unknown state" },
    { name: "undownloadable completion", record: { ...complete, download_ready: false }, message: "not downloadable" },
    { name: "negative row count", record: { ...complete, row_count: -1 }, message: "not downloadable" },
    { name: "missing row count", record: { ...complete, row_count: null }, message: "not downloadable" },
    { name: "fractional row count", record: { ...complete, row_count: 1.5 }, message: "not downloadable" },
  ])("rejects $name without retrying", async ({ record, message }) => {
    const f = fixture();
    const read = vi.fn(async () => record);
    await expect(waitForPortfolioExport("job", read, f.timing)).rejects.toThrow(message);
    expect(read).toHaveBeenCalledTimes(1);
    expect(f.timing.sleep).not.toHaveBeenCalled();
  });
  it("does not hide a failed status transport behind a retry", async () => {
    const f = fixture();
    const read = vi.fn(async () => { throw new Error("status transport failed"); });
    await expect(waitForPortfolioExport("job", read, f.timing)).rejects.toThrow("status transport failed");
    expect(read).toHaveBeenCalledTimes(1);
    expect(f.timing.sleep).not.toHaveBeenCalled();
  });
  it("never starts a second status read while the first is outstanding", async () => {
    const f = fixture();
    let finishFirst: (record: PortfolioExportCompletion) => void = () => {};
    const first = new Promise<PortfolioExportCompletion>(resolve => { finishFirst = resolve; });
    let active = 0;
    let maximum = 0;
    let calls = 0;
    const read = vi.fn(async (_timeout: number) => {
      active++;
      maximum = Math.max(maximum, active);
      try { return ++calls === 1 ? await first : complete; }
      finally { active--; }
    });
    const result = waitForPortfolioExport("job", read, f.timing);
    await Promise.resolve();
    expect(read).toHaveBeenCalledTimes(1);
    finishFirst(running);
    expect(await result).toEqual(complete);
    expect(read).toHaveBeenCalledTimes(2);
    expect(maximum).toBe(1);
  });
});
