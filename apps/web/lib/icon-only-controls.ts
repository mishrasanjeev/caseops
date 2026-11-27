import ts from "typescript";

/**
 * Source audit for icon-only controls (Nov 27 workbook, Aishwarya row 10).
 *
 * A button or link whose only visible content is an icon must carry an
 * accessible name and a tooltip that shows on hover and keyboard focus. The
 * shared `IconButton` primitive provides both and requires the label in its
 * type; this audit finds every raw `button`, `a`, `Button`, `Link` or Radix
 * `*.Trigger` / `*.Close` that renders no visible text and is not an
 * `IconButton`, so a new unlabeled icon-only control fails the inventory test.
 *
 * Unknown expressions such as `{label}` or `<CaseSummary />` count as visible
 * text: the audit flags only controls that provably show nothing but icons.
 */

export type IconOnlyControl = {
  file: string;
  line: number;
  tag: string;
  hasAccessibleName: boolean;
  /** Direct child of the shared `Tooltip`, which names it and shows the label. */
  inTooltip: boolean;
};

const INTERACTIVE_TAGS = new Set(["button", "a", "Button", "Link"]);
const ICON_NAME = /(^Icon$|Icon$|^Loader|^Spinner$)/;

function tagName(node: ts.JsxTagNameExpression): string {
  return node.getText();
}

function attributes(
  node: ts.JsxOpeningElement | ts.JsxSelfClosingElement,
): Map<string, ts.JsxAttribute> {
  const found = new Map<string, ts.JsxAttribute>();
  for (const property of node.attributes.properties) {
    if (ts.isJsxAttribute(property)) found.set(property.name.getText(), property);
  }
  return found;
}

function hasSpread(node: ts.JsxOpeningElement | ts.JsxSelfClosingElement): boolean {
  return node.attributes.properties.some((property) => ts.isJsxSpreadAttribute(property));
}

function isInteractive(tag: string, attrs: Map<string, ts.JsxAttribute>): boolean {
  if (INTERACTIVE_TAGS.has(tag)) return true;
  if (/\.(Trigger|Close)$/.test(tag) || /^[A-Z]\w*(Trigger|Close)$/.test(tag)) {
    return !attrs.has("asChild");
  }
  return false;
}

function classNameText(attrs: Map<string, ts.JsxAttribute>): string {
  const value = attrs.get("className")?.initializer;
  return value ? value.getText() : "";
}

function lucideIcons(source: ts.SourceFile): Set<string> {
  const names = new Set<string>();
  for (const statement of source.statements) {
    if (
      ts.isImportDeclaration(statement) &&
      ts.isStringLiteral(statement.moduleSpecifier) &&
      statement.moduleSpecifier.text === "lucide-react" &&
      statement.importClause?.namedBindings &&
      ts.isNamedImports(statement.importClause.namedBindings)
    ) {
      for (const element of statement.importClause.namedBindings.elements) {
        names.add(element.name.text);
      }
    }
  }
  return names;
}

function isIcon(tag: string, icons: Set<string>): boolean {
  return icons.has(tag) || ICON_NAME.test(tag);
}

function expressionShowsText(expression: ts.Expression, icons: Set<string>): boolean {
  if (ts.isParenthesizedExpression(expression)) {
    return expressionShowsText(expression.expression, icons);
  }
  if (
    ts.isStringLiteral(expression) ||
    ts.isNoSubstitutionTemplateLiteral(expression) ||
    ts.isTemplateExpression(expression) ||
    ts.isNumericLiteral(expression)
  ) {
    return expression.getText().replace(/^["'`]|["'`]$/g, "").trim().length > 0;
  }
  if (
    expression.kind === ts.SyntaxKind.NullKeyword ||
    expression.kind === ts.SyntaxKind.FalseKeyword ||
    expression.kind === ts.SyntaxKind.TrueKeyword ||
    (ts.isIdentifier(expression) && expression.text === "undefined")
  ) {
    return false;
  }
  if (ts.isJsxElement(expression) || ts.isJsxSelfClosingElement(expression) || ts.isJsxFragment(expression)) {
    return nodeShowsText(expression, icons);
  }
  if (ts.isConditionalExpression(expression)) {
    return (
      expressionShowsText(expression.whenTrue, icons) ||
      expressionShowsText(expression.whenFalse, icons)
    );
  }
  if (ts.isBinaryExpression(expression)) {
    const operator = expression.operatorToken.kind;
    if (operator === ts.SyntaxKind.AmpersandAmpersandToken) {
      return expressionShowsText(expression.right, icons);
    }
    if (
      operator === ts.SyntaxKind.BarBarToken ||
      operator === ts.SyntaxKind.QuestionQuestionToken
    ) {
      return (
        expressionShowsText(expression.left, icons) ||
        expressionShowsText(expression.right, icons)
      );
    }
  }
  // Identifiers, calls, maps and member reads may render text.
  return true;
}

function childrenShowText(children: ts.NodeArray<ts.JsxChild>, icons: Set<string>): boolean {
  return children.some((child) => {
    if (ts.isJsxText(child)) return child.text.trim().length > 0;
    if (ts.isJsxExpression(child)) {
      return child.expression ? expressionShowsText(child.expression, icons) : false;
    }
    return nodeShowsText(child, icons);
  });
}

function nodeShowsText(
  node: ts.JsxElement | ts.JsxSelfClosingElement | ts.JsxFragment,
  icons: Set<string>,
): boolean {
  if (ts.isJsxFragment(node)) return childrenShowText(node.children, icons);
  const opening = ts.isJsxElement(node) ? node.openingElement : node;
  const tag = tagName(opening.tagName);
  const attrs = attributes(opening);
  if (/\bsr-only\b/.test(classNameText(attrs))) return false;
  if (ts.isJsxSelfClosingElement(node)) {
    if (/^[a-z]/.test(tag)) return false;
    return !isIcon(tag, icons);
  }
  return childrenShowText(node.children, icons);
}

function controlShowsText(
  node: ts.JsxElement | ts.JsxSelfClosingElement,
  icons: Set<string>,
): boolean {
  if (ts.isJsxSelfClosingElement(node)) {
    // Content arrives through props; nothing to judge.
    return true;
  }
  return childrenShowText(node.children, icons);
}

function hasAccessibleName(attrs: Map<string, ts.JsxAttribute>): boolean {
  return attrs.has("aria-label") || attrs.has("aria-labelledby");
}

function wrappedInTooltip(node: ts.JsxElement | ts.JsxSelfClosingElement): boolean {
  const parent = node.parent;
  return ts.isJsxElement(parent) && tagName(parent.openingElement.tagName) === "Tooltip";
}

export function findIconOnlyControls(file: string, sourceText: string): IconOnlyControl[] {
  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const icons = lucideIcons(source);
  const found: IconOnlyControl[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxElement(node) || ts.isJsxSelfClosingElement(node)) {
      const opening = ts.isJsxElement(node) ? node.openingElement : node;
      const tag = tagName(opening.tagName);
      const attrs = attributes(opening);
      if (
        isInteractive(tag, attrs) &&
        !hasSpread(opening) &&
        !attrs.has("children") &&
        !controlShowsText(node, icons)
      ) {
        found.push({
          file,
          line: source.getLineAndCharacterOfPosition(opening.getStart()).line + 1,
          tag,
          hasAccessibleName: hasAccessibleName(attrs),
          inTooltip: wrappedInTooltip(node),
        });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

/** `IconButton` sites that also render visible text (use `Button` there). */
export function findTextIconButtons(file: string, sourceText: string): number[] {
  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const icons = lucideIcons(source);
  const lines: number[] = [];
  const visit = (node: ts.Node) => {
    if (
      ts.isJsxElement(node) &&
      tagName(node.openingElement.tagName) === "IconButton" &&
      childrenShowText(node.children, icons)
    ) {
      lines.push(source.getLineAndCharacterOfPosition(node.getStart()).line + 1);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return lines;
}
