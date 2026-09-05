import { expect, test } from "@playwright/test";
import { assertRevokedTurns, selectPrivateReleaseFixture } from "./support/private-release-fixtures";

const prefix = "IPLF-066B-ABCDEF123456";
const fixture = (iteration: number, status: "active" | "disposed" = "disposed") => ({
  id: String(iteration), matter_code: prefix + (iteration === 1 ? "" : `-R${iteration}`),
  title: "synthetic fixture", status, updated_at: "2026-09-05T00:00:00Z",
});

test("IPLF-066B recurring fixture selects active or latest terminal without reopening", () => {
  const rows = [fixture(1), fixture(2), fixture(10)];
  expect(selectPrivateReleaseFixture(rows, prefix).id).toBe("10");
  expect(selectPrivateReleaseFixture([...rows, fixture(11, "active")], prefix).id).toBe("11");
  expect(rows.every((row) => row.status === "disposed")).toBe(true);
  expect(() => selectPrivateReleaseFixture([], prefix)).toThrow("missing");
  expect(() => selectPrivateReleaseFixture([fixture(1, "active"), fixture(2, "active")], prefix)).toThrow("ambiguous");
  expect(() => selectPrivateReleaseFixture([{ ...fixture(1), matter_code: prefix + "-R1" }], prefix)).toThrow("colliding");
  expect(() => selectPrivateReleaseFixture([{ ...fixture(1), matter_code: "OTHER-" + prefix }], prefix)).toThrow("colliding");
  expect(() => selectPrivateReleaseFixture([{ ...fixture(1), status: "intake" }], prefix)).toThrow("lifecycle");
});

test("IPLF-066B retained proof rejects absent answers, leaked text, citations and actions", () => {
  const answer = { role: "assistant", render_status: "permission_changed", content: "Hidden after access changed.", citations: [], proposed_actions: [] };
  assertRevokedTurns([answer], "Aurora-fixture");
  for (const rows of [
    [], [{ ...answer, role: "user" }], [{ ...answer, render_status: "visible" }],
    [{ ...answer, content: "Aurora-fixture" }], [{ ...answer, citations: ["source"] }],
    [{ ...answer, proposed_actions: ["write"] }],
  ]) expect(() => assertRevokedTurns(rows, "Aurora-fixture")).toThrow();
});
