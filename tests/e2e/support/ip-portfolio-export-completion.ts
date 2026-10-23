export const PORTFOLIO_EXPORT_COMPLETION_MS = 15_000;
export const PORTFOLIO_EXPORT_MAX_READS = 16;

export type PortfolioExportCompletion = {
  id: string;
  status: string;
  download_ready: boolean;
  row_count: number | null;
};
type Clock = { now: () => number; sleep: (milliseconds: number) => Promise<void> };

const clock: Clock = {
  now: () => performance.now(),
  sleep: milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)),
};

export async function waitForPortfolioExport(
  jobId: string,
  read: (timeout: number) => Promise<PortfolioExportCompletion>,
  timing: Clock = clock,
): Promise<PortfolioExportCompletion> {
  // Preserve the accepted local async-job budget, independently of UI assertions.
  const deadline = timing.now() + PORTFOLIO_EXPORT_COMPLETION_MS;
  for (let count = 0; count < PORTFOLIO_EXPORT_MAX_READS; count++) {
    const remaining = deadline - timing.now();
    if (remaining <= 0) break;
    const record = await read(Math.min(5_000, remaining));
    if (timing.now() > deadline) break;
    if (record.id !== jobId) throw new Error("Portfolio export returned another job.");
    if (record.status === "failed") throw new Error("Portfolio export failed.");
    if (record.status === "completed") {
      if (!record.download_ready || typeof record.row_count !== "number"
        || !Number.isInteger(record.row_count) || record.row_count < 0) {
        throw new Error("Completed portfolio export is not downloadable.");
      }
      return record;
    }
    if (record.status !== "pending" && record.status !== "running") {
      throw new Error("Portfolio export returned an unknown state.");
    }
    await timing.sleep(Math.min(1_000, Math.max(0, deadline - timing.now())));
  }
  throw new Error("Portfolio export exceeded its bounded completion budget.");
}
