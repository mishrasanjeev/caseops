import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = ts.createSourceFile(
  "MatterScreen.tsx",
  readFileSync(
    new URL("../application/screens/MatterScreen.tsx", import.meta.url),
    "utf8",
  ),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);

function collect<T extends ts.Node>(
  guard: (node: ts.Node) => node is T,
  root: ts.Node = source,
): T[] {
  const found: T[] = [];
  const visit = (node: ts.Node) => {
    if (guard(node)) found.push(node);
    ts.forEachChild(node, visit);
  };
  visit(root);
  return found;
}

test("every note body exposes the immutable server identity on the actual native Text", () => {
  const bodyAttributes = collect(ts.isJsxAttribute).filter(
    (attribute) =>
      attribute.name.getText(source) === "testID" &&
      attribute.initializer &&
      ts.isJsxExpression(attribute.initializer) &&
      attribute.initializer.expression &&
      ts.isTemplateExpression(attribute.initializer.expression) &&
      attribute.initializer.expression.head.text === "note-body-",
  );
  assert.equal(bodyAttributes.length, 1);
  const attribute = bodyAttributes[0];
  assert.ok(attribute.initializer && ts.isJsxExpression(attribute.initializer));
  const expression = attribute.initializer.expression;
  assert.ok(expression && ts.isTemplateExpression(expression));
  assert.equal(expression.templateSpans.length, 1);
  assert.equal(
    expression.templateSpans[0].expression.getText(source),
    "note.id",
  );
  assert.equal(expression.templateSpans[0].literal.text, "");
  const opening = attribute.parent.parent;
  assert.ok(ts.isJsxOpeningElement(opening));
  assert.equal(opening.tagName.getText(source), "Text");
  assert.ok(ts.isJsxElement(opening.parent));
  assert.ok(
    collect(ts.isJsxExpression, opening.parent).some(
      (child) => child.expression?.getText(source) === "note.body",
    ),
  );
});

test("the newest note does not replace its stable body identity with a positional alias", () => {
  assert.equal(
    collect(ts.isStringLiteral).filter(
      (literal) => literal.text === "note-latest-body",
    ).length,
    0,
  );
});

test("the current-session revoke control is selected by the authoritative current flag, not its list index", () => {
  const sessions = ts.createSourceFile(
    "AccountDeviceSessions.tsx",
    readFileSync(
      new URL("../components/AccountDeviceSessions.tsx", import.meta.url),
      "utf8",
    ),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const controls = collect(ts.isJsxAttribute, sessions).filter((attribute) => {
    if (
      attribute.name.getText(sessions) !== "testID" ||
      !attribute.initializer ||
      !ts.isJsxExpression(attribute.initializer)
    )
      return false;
    const value = attribute.initializer.expression;
    return (
      value &&
      ts.isConditionalExpression(value) &&
      value.condition.getText(sessions) === "session.current" &&
      ts.isStringLiteral(value.whenTrue) &&
      value.whenTrue.text === "account-session-current-revoke"
    );
  });
  assert.equal(controls.length, 1);
  const control = controls[0].parent.parent;
  assert.ok(ts.isJsxSelfClosingElement(control));
  assert.equal(control.tagName.getText(sessions), "NativeButton");
});
