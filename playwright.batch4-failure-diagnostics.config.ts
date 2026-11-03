/** NONRELEASE scoped diagnostics; never a canonical production QA verdict. */
import { defineConfig } from "@playwright/test";
import canonical from "./playwright.prod-ram.config";

export const batch4DiagnosticCases = [
  { file: "ram-2026-10-31-control-crawl.spec.ts", title: "BUG-015 controls on /app/ip/specialist are usable or explain themselves" },
  { file: "ram-2026-10-31-invoice-pdf.spec.ts", title: "BUG-016 [prod-only] the reported invoices INVR-2026-028 and INVR-2026-068 download legible (read-only)" },
  { file: "ram-2026-10-31-watch.spec.ts", title: "BUG-014 journal capture: 'Class 45' with captured evidence is recorded, listed and shown on the hit; a bad class token is refused at its field" },
] as const;

const selected = canonical.projects?.filter((project) => project.name === "batch4-prod-chromium");
if (selected?.length !== 1) throw new Error("DIAGNOSTIC_PROJECT_REFUSED");
const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
export default defineConfig({
  ...canonical,
  workers: 1,
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  repeatEach: 1,
  reporter: [["./scripts/prod_playwright_reporter.cjs"]],
  projects: [{
    ...selected[0],
    name: "batch4-prod-chromium",
    dependencies: [],
    testMatch: batch4DiagnosticCases.map((item) => new RegExp(`${escape(item.file)}$`)),
    grep: new RegExp(`(?:${batch4DiagnosticCases.map((item) => escape(item.title)).join("|")})$`),
    fullyParallel: false,
    retries: 0,
    repeatEach: 1,
    use: { ...selected[0].use, trace: "off", screenshot: "off", video: "off" },
  }],
});
