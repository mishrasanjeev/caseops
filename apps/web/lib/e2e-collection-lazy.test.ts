// @vitest-environment node

import { readFileSync } from "node:fs";

import ts from "typescript";
import { expect, it } from "vitest";

const boundaries = [
  { file: "a11y.spec.ts", module: "@axe-core/playwright", binding: "AxeBuilder", uses: ["new AxeBuilder"] },
  { file: "public-content.spec.ts", module: "@axe-core/playwright", binding: "AxeBuilder", uses: ["new AxeBuilder"] },
  { file: "smoke/prod.spec.ts", module: "@axe-core/playwright", binding: "AxeBuilder", uses: ["new AxeBuilder", "new AxeBuilder"] },
  { file: "support/platform-report-qr.ts", module: "jsqr", binding: "jsQR", uses: ["jsQR"] },
  { file: "ram-2026-10-13-ip-portfolio.spec.ts", module: "jszip", binding: "JSZip", uses: ["JSZip.loadAsync"] },
  { file: "ram-2026-11-07-contracts.spec.ts", module: "jszip", binding: "JSZip", uses: ["new JSZip"] },
  { file: "ram-2026-11-11-contracts.spec.ts", module: "jszip", binding: "JSZip", uses: ["new JSZip"] },
];
const heavyModules = new Set(["@axe-core/playwright", "jsqr", "jszip", "pako"]);

function descendants(root: ts.Node): ts.Node[] {
  const nodes: ts.Node[] = [];
  function visit(node: ts.Node) {
    nodes.push(node);
    ts.forEachChild(node, visit);
  }
  visit(root);
  return nodes;
}

it.each(boundaries)("keeps $file heavy imports inside awaited async runtime bodies", ({ file, module, binding, uses }) => {
  const source = ts.createSourceFile(file, readFileSync(
    new URL(`../../../tests/e2e/${file}`, import.meta.url), "utf8",
  ), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const nodes = descendants(source);
  const eagerModules: string[] = [];
  const imports: ts.CallExpression[] = [];
  for (const node of nodes) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node))
      && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      if (heavyModules.has(node.moduleSpecifier.text)) eagerModules.push(node.moduleSpecifier.text);
    }
    if (ts.isCallExpression(node) && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
      const name = node.arguments[0].text;
      if (!heavyModules.has(name)) continue;
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        expect(name).toBe(module);
        imports.push(node);
      } else if (node.expression.getText(source) === "require") {
        eagerModules.push(name);
      }
    }
  }
  expect(eagerModules).toEqual([]);
  expect(imports).toHaveLength(uses.length);
  for (const [index, call] of imports.entries()) {
    const awaiting = call.parent;
    expect(ts.isAwaitExpression(awaiting)).toBe(true);
    const declaration = awaiting.parent;
    if (!ts.isVariableDeclaration(declaration)) throw new Error("Import must bind its awaited default export.");
    expect(declaration.name.getText(source)).toBe(`{ default: ${binding} }`);
    const statement = declaration.parent.parent;
    expect(ts.isVariableStatement(statement)).toBe(true);
    const body = statement.parent;
    if (!ts.isBlock(body) || !(ts.isFunctionDeclaration(body.parent)
      || ts.isFunctionExpression(body.parent) || ts.isArrowFunction(body.parent))) {
      throw new Error("Import must be an unconditional statement in the runtime function body.");
    }
    expect(body.parent.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.AsyncKeyword)).toBe(true);
    const consumers = descendants(body).filter(node =>
      (ts.isNewExpression(node) && `new ${node.expression.getText(source)}` === uses[index])
      || (ts.isCallExpression(node) && node.expression.getText(source) === uses[index]),
    );
    expect(consumers).toHaveLength(1);
    expect(consumers[0].getStart(source)).toBeGreaterThan(statement.getEnd());
  }
});

it.each([
  { file: "support/draft_pdf_production_20261111.ts", imports: 1, validators: ["authContext", "draftSchema"] },
  { file: "ram-2026-10-22-drafting.prod.spec.ts", imports: 2, validators: ["authContext", "draftSchema"] },
  { file: "ram-2026-11-11-bugs.spec.ts", imports: 2, validators: ["authContext", "authSession"] },
])("defers $file canonical validators without replacing their response checks", ({ file, imports, validators }) => {
  const source = ts.createSourceFile(file, readFileSync(
    new URL(`../../../tests/e2e/${file}`, import.meta.url), "utf8",
  ), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const nodes = descendants(source);
  const modulePath = (value: string) => value.endsWith("/lib/api/schemas");
  for (const node of nodes) {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)
      && modulePath(node.moduleSpecifier.text)) {
      expect(node.importClause?.isTypeOnly).toBe(true);
    }
  }
  const deferred = nodes.filter(node => ts.isCallExpression(node)
    && node.expression.kind === ts.SyntaxKind.ImportKeyword
    && node.arguments[0] && ts.isStringLiteral(node.arguments[0])
    && modulePath(node.arguments[0].text));
  expect(deferred).toHaveLength(imports);
  for (const call of deferred) {
    expect(ts.isAwaitExpression(call.parent)).toBe(true);
    let runtime = call.parent;
    while (runtime.parent && !ts.isFunctionDeclaration(runtime)
      && !ts.isArrowFunction(runtime) && !ts.isFunctionExpression(runtime)) runtime = runtime.parent;
    if (!ts.isFunctionDeclaration(runtime) && !ts.isArrowFunction(runtime)
      && !ts.isFunctionExpression(runtime)) throw new Error("Canonical schemas must load inside a runtime function.");
    expect(runtime.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.AsyncKeyword)).toBe(true);
  }
  for (const validator of validators) {
    expect(nodes.some(node => ts.isCallExpression(node)
      && node.expression.getText(source) === `${validator}.safeParse`)).toBe(true);
  }
});
