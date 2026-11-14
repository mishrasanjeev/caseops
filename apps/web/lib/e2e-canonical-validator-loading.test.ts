// @vitest-environment node

import { readFileSync } from "node:fs";

import ts from "typescript";
import { expect, it } from "vitest";

it.each([
  { file: "support/draft_pdf_production_20261111.ts", validators: ["authContext", "draftSchema"] },
  { file: "ram-2026-10-22-drafting.prod.spec.ts", validators: ["authContext", "draftSchema"] },
  { file: "ram-2026-11-11-bugs.spec.ts", validators: ["authContext", "authSession"] },
])("keeps $file canonical validators on the verified Playwright TypeScript loader path", ({ file, validators }) => {
  const source = ts.createSourceFile(file, readFileSync(
    new URL(`../../../tests/e2e/${file}`, import.meta.url), "utf8",
  ), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
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
