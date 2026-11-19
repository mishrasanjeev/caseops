// @vitest-environment node

import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import vm from "node:vm";

import ts from "typescript";
import { expect, it, vi } from "vitest";

import * as draftPolicy from "../../../tests/e2e/support/draft_pdf_production_policy_20261111";

it.each([
  { file: "support/draft_pdf_production_20261111.ts", validators: ["authContext", "draftSchema"],
    url: new URL("../../../tests/e2e/support/draft_pdf_production_20261111.ts", import.meta.url) },
  { file: "ram-2026-10-22-drafting.prod.spec.ts", validators: ["authContext", "draftSchema"],
    url: new URL("../../../tests/e2e/ram-2026-10-22-drafting.prod.spec.ts", import.meta.url) },
  { file: "ram-2026-11-11-bugs.spec.ts", validators: ["authContext", "authSession"],
    url: new URL("../../../tests/e2e/ram-2026-11-11-bugs.spec.ts", import.meta.url) },
  { file: "drafting-formats20261115.spec.ts", validators: ["draftSchema"],
    url: new URL("../../../tests/e2e/drafting-formats20261115.spec.ts", import.meta.url) },
])("keeps $file canonical validators on the verified Playwright TypeScript loader path", ({ file, validators, url }) => {
  const source = ts.createSourceFile(file, readFileSync(url, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const nodes: ts.Node[] = [];
  function visit(node: ts.Node) {
    nodes.push(node);
    ts.forEachChild(node, visit);
  }
  visit(source);
  const canonical = (value: string) => value.endsWith("/lib/api/schemas");
  const imports = nodes.filter(node => ts.isImportDeclaration(node)
    && ts.isStringLiteral(node.moduleSpecifier) && canonical(node.moduleSpecifier.text));
  expect(imports).toHaveLength(1);
  const declaration = imports[0] as ts.ImportDeclaration;
  expect(declaration.importClause?.isTypeOnly).toBe(true);
  const bindings = declaration.importClause?.namedBindings;
  if (!bindings || !ts.isNamedImports(bindings)) throw new Error("Canonical validators must be named imports.");
  expect(bindings.elements.length).toBeGreaterThan(0);
  const helperImports = nodes.filter(node => ts.isImportDeclaration(node)
    && ts.isStringLiteral(node.moduleSpecifier) && node.moduleSpecifier.text.endsWith("/canonical-api-validators"));
  expect(helperImports).toHaveLength(1);
  const helper = helperImports[0] as ts.ImportDeclaration;
  expect(helper.importClause?.isTypeOnly).toBe(false);
  expect(helper.importClause?.namedBindings?.getText(source)).toBe("{ canonicalApiValidators }");
  const loaders = nodes.filter(node => ts.isCallExpression(node)
    && node.expression.getText(source) === "canonicalApiValidators");
  expect(loaders.length).toBeGreaterThan(0);
  for (const call of loaders) {
    let parent: ts.Node | undefined = call.parent;
    while (parent && !ts.isFunctionLike(parent)) parent = parent.parent;
    expect(parent, "No validator evaluation during metadata collection").toBeDefined();
  }
  expect(nodes.some(node => ts.isCallExpression(node)
    && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(source) === "require")
    && node.arguments[0] && ts.isStringLiteral(node.arguments[0])
    && canonical(node.arguments[0].text))).toBe(false);
  for (const validator of validators) {
    expect(nodes.some(node => ts.isBindingElement(node) && node.name.getText(source) === validator
      && ts.isVariableDeclaration(node.parent.parent)
      && node.parent.parent.initializer?.getText(source) === "canonicalApiValidators()")).toBe(true);
    expect(nodes.some(node => ts.isCallExpression(node)
      && node.expression.getText(source) === `${validator}.safeParse`)).toBe(true);
  }
});

it("uses only the literal canonical module through Playwright's native synchronous TypeScript hook", () => {
  const text = readFileSync(new URL("../../../tests/e2e/support/canonical-api-validators.ts", import.meta.url), "utf8");
  const source = ts.createSourceFile("loader.ts", text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  expect(source.statements).toHaveLength(1);
  const fn = source.statements[0];
  if (!ts.isFunctionDeclaration(fn) || !fn.body) throw new Error("Only a journey-time loader is admitted.");
  expect(fn.name?.text).toBe("canonicalApiValidators");
  expect(fn.body.statements).toHaveLength(1);
  const statement = fn.body.statements[0];
  if (!ts.isReturnStatement(statement) || !statement.expression || !ts.isCallExpression(statement.expression)) {
    throw new Error("Return the actual canonical exports, never proxies or copied validators.");
  }
  expect(statement.expression.expression.getText(source)).toBe("require");
  expect(statement.expression.arguments.map(argument => argument.getText(source)))
    .toEqual(['"../../../apps/web/lib/api/schemas"']);
});

function productionDraftSource() {
  return ts.createSourceFile("draft_pdf_production_20261111.ts", readFileSync(
    new URL("../../../tests/e2e/support/draft_pdf_production_20261111.ts", import.meta.url), "utf8",
  ), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
}

it.each(["version", "body"])("rejects reported Draft %s drift before render/export without a mutation", async fault => {
  const source = productionDraftSource();
  const constants = source.statements.filter(node => ts.isVariableStatement(node));
  const functions = source.statements.filter(node => ts.isFunctionDeclaration(node));
  expect(constants.flatMap(node => node.declarationList.declarations.map(item => item.name.getText(source))))
    .toEqual(["hash", "fingerprint", "mediaOff"]);
  expect(functions.map(node => node.name?.text)).toEqual(["productionDraftPdfJourney"]);
  const target = draftPolicy.reportedDraftTarget;
  const retained = { id: target.draftId, matter_id: target.matterId, company_id: "tenant-unit",
    current_version_id: fault === "version" ? "different-version" : target.versionId,
    versions: [{ id: target.versionId, body: "Synthetic unreviewed unit source" }] };
  const before = JSON.stringify(retained), reads: string[] = [], attemptedMutations: string[] = [];
  const forbiddenWrite = vi.fn(async () => { throw new Error("Original mutation forbidden"); });
  const fill = vi.fn(async () => {}), click = vi.fn(async () => {});
  const page = {
    goto: vi.fn(async () => {}), locator: vi.fn(() => ({ fill })),
    getByRole: vi.fn(() => ({ click })), on: vi.fn(),
    waitForResponse: vi.fn(async () => ({ status: () => 200 })), waitForURL: vi.fn(async () => {}),
    request: { post: forbiddenWrite, patch: forbiddenWrite, delete: forbiddenWrite, get: vi.fn(async (url: string) => {
      const pathname = new URL(url).pathname;
      reads.push(pathname);
      return { status: () => 200, json: async () => pathname === "/api/auth/me" ? {
        company: { id: "tenant-unit", slug: "test-legal", is_active: true },
        user: { email: "ram@testfirm.com", is_active: true }, membership: { is_active: true },
      } : retained };
    }) },
  };
  let route: (value: unknown) => Promise<unknown>;
  const browserContext = { newPage: vi.fn(async () => page), addInitScript: vi.fn(async () => {}),
    route: vi.fn(async (_pattern: string, handler: typeof route) => { route = handler; }), close: vi.fn(async () => {}) };
  const browser = { newContext: vi.fn(async () => browserContext) };
  const assertDraftPdfRender = vi.fn(async () => { throw new Error("Rendering a mismatched original is forbidden"); });
  const info = { config: { workers: 1 }, project: { retries: 0, use: { trace: "off", screenshot: "off", video: "off" } },
    annotations: [], attach: vi.fn(async () => {}) };
  const sourceGuard = vi.fn(draftPolicy.assertReportedDraftSource);
  const context = vm.createContext({ ...draftPolicy, exports: {}, Buffer, URL, createHash, expect,
    assertReportedDraftSource: sourceGuard,
    devices: {}, noPaidProviderHeaders: { "X-CaseOps-Automated-Test": "no-paid-providers" },
    canonicalApiValidators: () => ({ authContext: { safeParse: (data: unknown) => ({ success: true, data }) },
      draft: { safeParse: (data: unknown) => ({ success: true, data }) } }),
    assertPublicReleaseIdentity: vi.fn(async () => {}), assertDraftPdfRender,
    process: { env: { PROD_API_BASE_URL: "https://api.caseops.ai", CASEOPS_EXPECTED_RELEASE_SHA: "a".repeat(40),
      CASEOPS_RAM_PROD_SLUG: "test-legal", CASEOPS_RAM_PROD_EMAIL: "ram@testfirm.com",
      CASEOPS_RAM_PROD_PASSWORD: "Synthetic-unit-secret-only" } },
  });
  // Extract every declaration and bind every runtime import used by the journey.
  vm.runInContext(ts.transpileModule([...constants, ...functions].map(node => node.getText(source)).join("\n"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText, context);
  await expect(context.exports.productionDraftPdfJourney(browser, "https://caseops.ai", info, false))
    .rejects.toThrow("failed at authorized-persisted-version; private details omitted");
  expect(page.goto).toHaveBeenCalledTimes(1);
  expect(reads).toEqual(["/api/auth/me", `/api/matters/${target.matterId}/drafts/${target.draftId}`]);
  expect(assertDraftPdfRender).not.toHaveBeenCalled();
  expect(sourceGuard).toHaveBeenCalledExactlyOnceWith(retained, expect.any(Function));
  expect(sourceGuard.mock.results[0].type).toBe("throw");
  expect(sourceGuard.mock.results[0].value.message).toMatch(/Reported draft.*differs/);
  expect(forbiddenWrite).not.toHaveBeenCalled();
  expect(info.attach).not.toHaveBeenCalled();
  expect(info.annotations).toEqual([{
    type: "caseops-b5-failure-stage", description: "reported-draft:authorized-persisted-version",
  }]);
  expect(JSON.stringify(info.annotations)).not.toContain(retained.versions[0].body);
  expect(JSON.stringify(retained)).toBe(before);
  expect(browserContext.close).toHaveBeenCalledTimes(1);
  for (const method of ["POST", "PATCH", "DELETE"]) {
    const abort = vi.fn(async () => {}), forward = vi.fn(async () => { attemptedMutations.push(method); });
    await route!({ request: () => ({ url: () => `https://api.caseops.ai/api/matters/${target.matterId}/drafts/${target.draftId}`,
      method: () => method, headers: () => ({ "x-caseops-automated-test": "no-paid-providers" }) }), abort, continue: forward });
    expect(abort).toHaveBeenCalledExactlyOnceWith("blockedbyclient");
    expect(forward).not.toHaveBeenCalled();
  }
  expect(attemptedMutations).toEqual([]);
});

it("emits only the bounded reported-Draft annotation after final source and read-only assertions", () => {
  const source = productionDraftSource();
  const nodes: ts.Node[] = [];
  const visit = (node: ts.Node) => { nodes.push(node); ts.forEachChild(node, visit); };
  visit(source);
  const pushes = nodes.filter(node => ts.isCallExpression(node)
    && node.expression.getText(source) === "info.annotations.push");
  expect(pushes).toHaveLength(2);
  const typed = (type: string) => pushes.filter(node => {
    const argument = (node as ts.CallExpression).arguments[0];
    return argument && ts.isObjectLiteralExpression(argument) && argument.properties.some(property =>
      ts.isPropertyAssignment(property) && property.name.getText(source) === "type"
      && ts.isStringLiteral(property.initializer) && property.initializer.text === type);
  });
  expect(typed("caseops-b5-reported-draft")).toHaveLength(1);
  expect(typed("caseops-b5-failure-stage")).toHaveLength(1);
  const push = typed("caseops-b5-reported-draft")[0] as ts.CallExpression;
  const target = draftPolicy.reportedDraftTarget;
  const info = { annotations: [] as Array<{ type: string; description: string }> };
  const hash = vi.fn(() => target.bodySha256);
  const context = vm.createContext({ info, settings: target,
    version: { id: target.versionId, body: "Synthetic unit source, never serialized" }, hash, attemptedMutations: 0 });
  vm.runInContext(ts.transpileModule(push.getText(source), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText, context);
  expect(info.annotations).toHaveLength(1);
  expect(info.annotations[0].type).toBe("caseops-b5-reported-draft");
  expect(Buffer.byteLength(info.annotations[0].description, "utf8")).toBeLessThan(512);
  expect(JSON.parse(info.annotations[0].description)).toEqual({ schema_version: 1, status: "READ_ONLY_PARITY_VERIFIED",
    matter_id: target.matterId, draft_id: target.draftId, version_id: target.versionId,
    body_sha256: target.bodySha256, unchanged: true, attempted_mutations: 0 });
  expect(hash).toHaveBeenCalledExactlyOnceWith("Synthetic unit source, never serialized");
  const preceding = source.text.slice(0, push.pos);
  expect(preceding.lastIndexOf("await unchanged();")).toBeGreaterThan(preceding.lastIndexOf('stage = "reload-parity"'));
  expect(preceding.lastIndexOf("attemptedMutations === 0")).toBeGreaterThan(preceding.lastIndexOf("await unchanged();"));
});


it.each([
  { label: "reported Draft", file: "draft_pdf_production_20261111.ts", prefix: "reported-draft:",
    stages: ["release-before-login", "reporter-login", "authorized-persisted-version", "initial-preview",
      "export-http-<status>", "citation-review-guard", "auto-profile-parity", "selected-profile-parity", "reload-parity",
      "whole-dto-unchanged", "read-only-boundary"] },
  { label: "reported contract", file: "bugs5_contract_reported_20261111.ts", prefix: "reported-contract:",
    stages: ["identity", "original-metadata-controls", "original-indexed-pdf-preview",
      "original-preview-observer-admission", "original-preview-request", "original-preview-browser-digest",
      "original-preview-visible-canvas", "original-preview-visible-ink", "original-manual-term-controls", "unchanged-source"] },
])("keeps $label failure phases bounded and separate from successful evidence", ({ file, prefix, stages }) => {
  const source = ts.createSourceFile(file, readFileSync(
    new URL(`../../../tests/e2e/support/${file}`, import.meta.url), "utf8",
  ), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const nodes: ts.Node[] = [];
  function visit(node: ts.Node) { nodes.push(node); ts.forEachChild(node, visit); }
  visit(source);
  const calls = nodes.filter((node): node is ts.CallExpression => ts.isCallExpression(node)
    && node.expression.getText(source) === "info.annotations.push");
  const failures = calls.filter(call => ts.isObjectLiteralExpression(call.arguments[0])
    && call.arguments[0].properties.some(property => ts.isPropertyAssignment(property)
      && property.name.getText(source) === "type" && ts.isStringLiteral(property.initializer)
      && property.initializer.text === "caseops-b5-failure-stage"));
  expect(failures).toHaveLength(1);
  const argument = failures[0].arguments[0];
  if (!ts.isObjectLiteralExpression(argument)) throw new Error("Failure phase must be an exact record.");
  expect(argument.properties.map(property => property.name?.getText(source))).toEqual(["type", "description"]);
  const property = argument.properties[1];
  if (!ts.isPropertyAssignment(property) || !ts.isTemplateExpression(property.initializer)) {
    throw new Error("Only the phase label may be interpolated.");
  }
  expect(property.initializer.head.text).toBe(prefix);
  expect(property.initializer.templateSpans.map(span => [span.expression.getText(source), span.literal.text]))
    .toEqual([["stage", ""]]);
  let parent: ts.Node | undefined = failures[0].parent;
  while (parent && !ts.isCatchClause(parent)) parent = parent.parent;
  expect(parent && ts.isCatchClause(parent)).toBe(true);
  const initial = nodes.filter((node): node is ts.VariableDeclaration => ts.isVariableDeclaration(node)
    && node.name.getText(source) === "stage");
  expect(initial).toHaveLength(1);
  const first = initial[0].initializer;
  if (!first || !ts.isStringLiteral(first)) throw new Error("Phase starts at a reviewed literal.");
  const actual = [first.text];
  for (const node of nodes) {
    if (!ts.isBinaryExpression(node) || node.left.getText(source) !== "stage") continue;
    expect(node.operatorToken.kind).toBe(ts.SyntaxKind.EqualsToken);
    if (ts.isStringLiteral(node.right)) actual.push(node.right.text);
    else {
      if (!ts.isTemplateExpression(node.right)) throw new Error("Unbounded phase input rejected.");
      expect(node.right.head.text).toBe("export-http-");
      expect(node.right.templateSpans.map(span => [span.expression.getText(source), span.literal.text]))
        .toEqual([["initial.status()", ""]]);
      actual.push("export-http-<status>");
    }
  }
  expect(actual).toEqual(stages);
});
