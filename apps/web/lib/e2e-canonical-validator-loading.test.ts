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
  expect(declaration.importClause?.isTypeOnly).toBe(false);
  const bindings = declaration.importClause?.namedBindings;
  if (!bindings || !ts.isNamedImports(bindings)) throw new Error("Canonical validators must be named imports.");
  const importedValidators = bindings.elements.filter(element => !element.isTypeOnly).map(element => element.name.text);
  expect(importedValidators.sort()).toEqual([...validators].sort());
  expect(nodes.some(node => ts.isCallExpression(node)
    && node.expression.kind === ts.SyntaxKind.ImportKeyword
    && node.arguments[0] && ts.isStringLiteral(node.arguments[0])
    && canonical(node.arguments[0].text))).toBe(false);
  for (const validator of validators) {
    expect(nodes.some(node => ts.isCallExpression(node)
      && node.expression.getText(source) === `${validator}.safeParse`)).toBe(true);
  }
});
