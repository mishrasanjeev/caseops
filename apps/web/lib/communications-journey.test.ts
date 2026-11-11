// @vitest-environment node

import { readFileSync } from "node:fs";

import ts from "typescript";
import { expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("./api/client", () => ({ apiRequest: request }));

import { createMatter } from "./api/endpoints";

it("observes the canonical Matter-create POST in the dated communications journey", async () => {
  const source = ts.createSourceFile("communications.spec.ts", readFileSync(
    new URL("../../../tests/e2e/ram-2026-11-11-bugs.spec.ts", import.meta.url), "utf8",
  ), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const observedPaths: string[] = [];
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === "matterSaved"
      && node.initializer && ts.isCallExpression(node.initializer)
      && node.initializer.expression.getText(source) === "responseFor") {
      const [path] = node.initializer.arguments;
      if (path && ts.isStringLiteral(path)) observedPaths.push(path.text);
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  expect(observedPaths).toHaveLength(1);

  // Stop before response parsing: only the actual adapter's route is under test.
  const stopped = new Error("Offline route observation only");
  request.mockRejectedValueOnce(stopped);
  const input = { title: "Communications QA", matter_code: "COMMS-UNIT" };
  await expect(createMatter(input)).rejects.toBe(stopped);
  expect(request).toHaveBeenCalledExactlyOnceWith("/api/matters/", { method: "POST", body: input });
  expect(request.mock.calls[0][0]).toBe(observedPaths[0]);
});
