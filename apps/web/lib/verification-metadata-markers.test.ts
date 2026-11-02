import { execFileSync } from "node:child_process";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(import.meta.dirname, "../../..");
const fixtures = path.join(root, "tests/e2e/fixtures");
const marker = "no-paid-providers";
const powershell = process.platform === "win32" ? "powershell" : "pwsh";

function powershellProbes() {
  return JSON.parse(execFileSync(powershell, ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
    "-File", path.join(fixtures, "metadata-marker-probes.ps1"), "-RepoRoot", root],
  { encoding: "utf8", timeout: 30000 }));
}

function nodeProbe(mode: string, code?: string) {
  return JSON.parse(execFileSync(process.execPath, [path.join(fixtures, "metadata-marker-node.cjs"), root, mode,
    ...(code ? [code] : [])], { encoding: "utf8", timeout: 15000 }));
}

describe("automated local metadata reads retain provider isolation", () => {
  it.each(["functional", "public"])("%s startup probe sends the marker on a real loopback GET", (mode) => {
    const result = nodeProbe(mode);
    expect(result.external_requests).toBe(0);
    expect(result.server_closed).toBe(true);
    expect(result.records).toHaveLength(1);
    expect(result.records[0].headers["x-caseops-automated-test"]).toBe(marker);
  });

  it("all five Docker host readiness/identity commands pass the actual header argument", () => {
    const result = powershellProbes();
    expect(path.resolve(result.repo_root)).toBe(root);
    expect(result.operational_harness_executed).toBe(false);
    expect(result.rest_calls.map((call: { uri: string }) => call.uri)).toEqual([
      "http://127.0.0.1:18001/api/health", "http://127.0.0.1:18001/api/build",
      "http://127.0.0.1:18002/api/release-identity", "http://127.0.0.1:18003/api/health",
      "http://127.0.0.1:18001/api/health",
    ]);
    for (const call of result.rest_calls) expect(call.headers["X-CaseOps-Automated-Test"]).toBe(marker);
    expect(result.rest_calls[3].timeout).toBe(5);
  });

  it("both web-container metadata fetches retain the marker and original deadlines", () => {
    const result = nodeProbe("embedded", powershellProbes().server_origin_code);
    expect(result.external_requests).toBe(0);
    expect(result.records.map((call: { url: string }) => call.url)).toEqual([
      "http://api:8000/api/health", "http://api:8000/api/build",
    ]);
    for (const call of result.records) {
      expect(call.headers["X-CaseOps-Automated-Test"]).toBe(marker);
      expect(call.deadlinePresent).toBe(true);
    }
  });

  it("cold-start diagnostic urllib requests retain the marker without launching Docker", () => {
    const python = process.platform === "win32" ? path.join(root, "apps/api/.venv/Scripts/python.exe") : "python3";
    const output = execFileSync(python, [path.join(fixtures, "metadata-marker-health.py"),
      powershellProbes().cold_health_code], { encoding: "utf8", timeout: 10000 });
    const result = JSON.parse(output.trim().split(/\r?\n/).find((line) => line.startsWith("REQUESTS "))!.slice(9));
    expect(result.external_requests).toBe(0);
    expect(result.records).toHaveLength(1);
    const headers = Object.fromEntries(Object.entries(result.records[0].headers).map(([key, value]) => [key.toLowerCase(), value]));
    expect(headers["x-caseops-automated-test"]).toBe(marker);
    expect(result.records[0].timeout).toBe(1);
  });
});
