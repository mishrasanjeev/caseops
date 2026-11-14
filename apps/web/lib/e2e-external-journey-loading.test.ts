// @vitest-environment node
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { expect, it } from "vitest";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const targets = [
  ["a11y.spec.ts", "loadAxeBuilder"], ["public-content.spec.ts", "loadAxeBuilder"],
  ["support/platform-report-qr.ts", "loadJsQR"],
  ["ram-2026-10-13-ip-portfolio.spec.ts", "loadJSZip"],
  ["ram-2026-11-07-contracts.spec.ts", "loadJSZip"],
  ["ram-2026-11-11-contracts.spec.ts", "loadJSZip"],
] as const;
const external = new Set(["@axe-core/playwright", "jsqr", "jszip"]);

it.each(targets)("keeps %s external pure dependencies inside journey-time calls", (file, loader) => {
  const source = ts.createSourceFile(file, readFileSync(path.join(root, "tests/e2e", file), "utf8"), ts.ScriptTarget.Latest, true);
  const nodes: ts.Node[] = [];
  function visit(node: ts.Node) { nodes.push(node); ts.forEachChild(node, visit); }
  visit(source);
  expect(nodes.some(node => ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)
    && external.has(node.moduleSpecifier.text))).toBe(false);
  const imports = nodes.filter(node => ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)
    && node.moduleSpecifier.text.endsWith("/external-journey-loaders"));
  expect(imports).toHaveLength(1);
  const declaration = imports[0] as ts.ImportDeclaration;
  expect(declaration.importClause?.isTypeOnly).toBe(false);
  expect(declaration.importClause?.namedBindings?.getText(source)).toBe(`{ ${loader} }`);
  const calls = nodes.filter(node => ts.isCallExpression(node) && node.expression.getText(source) === loader);
  expect(calls).toHaveLength(1);
  for (const call of calls) {
    let parent = call.parent;
    while (parent && !ts.isFunctionLike(parent)) parent = parent.parent;
    expect(parent, "Native listing cannot invoke external libraries").toBeDefined();
  }
});

it("keeps literal native requires without proxy, fallback or copied implementations", () => {
  const source = ts.createSourceFile("loader.ts", readFileSync(path.join(root, "tests/e2e/support/external-journey-loaders.ts"), "utf8"), ts.ScriptTarget.Latest, true);
  expect(source.statements).toHaveLength(3);
  for (const [index, [name, returned]] of [
    ["loadAxeBuilder", 'require("@axe-core/playwright").default'],
    ["loadJsQR", 'require("jsqr")'], ["loadJSZip", 'require("jszip")'],
  ].entries()) {
    const node = source.statements[index];
    if (!ts.isFunctionDeclaration(node) || !node.body) throw new Error("Only journey-time loader functions are admitted.");
    expect(node.name?.text).toBe(name);
    expect(node.body.statements).toHaveLength(1);
    const statement = node.body.statements[0];
    if (!ts.isReturnStatement(statement)) throw new Error("Return the real native module.");
    expect(statement.expression?.getText(source)).toBe(returned);
  }
});

it("runs actual ZIP, QR and accessibility libraries in a native offline Playwright worker", () => {
  const dir = mkdtempSync(path.join(os.tmpdir(), "caseops-external-worker-"));
  const pw = path.join(root, "node_modules/@playwright/test");
  const executablePath = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"].find(file => existsSync(file));
  writeFileSync(path.join(dir, "playwright.config.cjs"), `module.exports = { testDir: __dirname, testMatch: 'external.spec.ts', workers: 1, retries: 0, repeatEach: 1, timeout: 5000, reporter: [['json']], outputDir: ${JSON.stringify(path.join(dir, "results"))}, use: { launchOptions: ${JSON.stringify(executablePath ? { executablePath } : {})}, offline: true, serviceWorkers: 'block', trace: 'off', screenshot: 'off', video: 'off', extraHTTPHeaders: { 'X-CaseOps-Automated-Test': 'no-paid-providers' } } };`);
  writeFileSync(path.join(dir, "external.spec.ts"), `
import { test, expect } from ${JSON.stringify(pw)};
import { loadAxeBuilder, loadJsQR, loadJSZip } from ${JSON.stringify(path.join(root, "tests/e2e/support/external-journey-loaders.ts"))};
import { renderedTotpSecret } from ${JSON.stringify(path.join(root, "tests/e2e/support/platform-report-qr.ts"))};
const fromRoot = require('node:module').createRequire(${JSON.stringify(path.join(root, "package.json"))});
test.beforeAll(() => {
  const deny = () => { throw new Error('Network forbidden in external loader regression'); };
  for (const name of ['node:http', 'node:https']) { const transport = require(name); transport.request = deny; transport.get = deny; }
  const net = require('node:net'); net.connect = deny; net.createConnection = deny;
  require('node:dns').lookup = deny; globalThis.fetch = deny;
  for (const name of ['@axe-core/playwright', 'jsqr', 'jszip']) expect(require.cache[fromRoot.resolve(name)]).toBeUndefined();
});
test('native ZIP constructor and loadAsync preserve real XLSX and synthetic DOCX bytes', async () => {
  const JSZip = loadJSZip();
  expect(JSZip).toBe(fromRoot('jszip')); expect(loadJSZip()).toBe(JSZip);
  const zip = new JSZip(); expect(zip).toBeInstanceOf(JSZip);
  zip.file('word/document.xml', '<doc>Synthetic – not a legal agreement.</doc>');
  const bytes = await zip.generateAsync({ type: 'nodebuffer' });
  expect(await (await loadJSZip().loadAsync(bytes)).file('word/document.xml').async('string')).toBe('<doc>Synthetic – not a legal agreement.</doc>');
  const original = require('node:fs').readFileSync(${JSON.stringify(path.join(root, "tests/e2e/fixtures/ip-portfolio-native-dates-20261013.xlsx"))});
  const book = await loadJSZip().loadAsync(original); const sheet = await book.file('xl/worksheets/sheet1.xml').async('string');
  expect(sheet).toContain('Synthetic native Excel date preview');
  book.file('xl/worksheets/sheet1.xml', sheet.replace('Synthetic native Excel date preview', 'Synthetic worker mark'));
  expect(await (await loadJSZip().loadAsync(await book.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }))).file('xl/worksheets/sheet1.xml').async('string')).toContain('Synthetic worker mark');
  await expect(loadJSZip().loadAsync(Buffer.from('not a ZIP'))).rejects.toThrow();
});
test('native QR pixels round-trip the real helper and reject a mismatched enrollment', async ({ page }) => {
  await page.route('**/*', route => route.abort('blockedbyclient'));
  expect(require.cache[fromRoot.resolve('jsqr')]).toBeUndefined();
  const account = 'synthetic@example.invalid', secret = 'JBSWY3DPEHPK3PXP';
  const url = 'otpauth://totp/' + encodeURIComponent('CaseOps Reports:' + account) + '?algorithm=SHA1&digits=6&issuer=CaseOps%20Reports&period=30&secret=' + secret;
  const React = fromRoot('react'); const render = fromRoot('react-dom/server').renderToStaticMarkup;
  const svg = render(React.createElement(fromRoot('qrcode.react').QRCodeSVG, { value: url, size: 256, marginSize: 4, level: 'M', role: 'img', 'aria-label': 'Authenticator setup QR code' }));
  await page.setContent(svg);
  expect(await renderedTotpSecret(page, { secret, otpauth_url: url }, account)).toBe(secret);
  expect(loadJsQR()).toBe(fromRoot('jsqr'));
  await expect(renderedTotpSecret(page, { secret: 'AAAAAAAAAAAAAAAA', otpauth_url: url }, account)).rejects.toThrow();
  expect(loadJsQR()(new Uint8ClampedArray(256 * 256 * 4).fill(255), 256, 256)).toBeNull();
});
test('native accessibility builder retains its instance and detects a real unnamed button', async ({ page }) => {
  await page.route('**/*', route => route.abort('blockedbyclient'));
  expect(require.cache[fromRoot.resolve('@axe-core/playwright')]).toBeUndefined();
  const AxeBuilder = loadAxeBuilder(); expect(AxeBuilder).toBe(fromRoot('@axe-core/playwright').default);
  await page.setContent('<!doctype html><html lang="en"><head><title>Synthetic</title></head><body><main><h1>Worker fixture</h1><button></button></main></body></html>');
  const builder = new (loadAxeBuilder())({ page }); expect(builder).toBeInstanceOf(AxeBuilder);
  const result = await builder.withTags(['wcag2a']).analyze();
  expect(result.violations.some(row => row.id === 'button-name')).toBe(true);
});
`);
  const env: NodeJS.ProcessEnv = { NODE_ENV: "test", CI: "1", TEMP: dir, TMP: dir };
  for (const key of ["PATH", "Path", "SystemRoot", "WINDIR", "HOME", "USERPROFILE"]) if (process.env[key]) env[key] = process.env[key];
  const result = spawnSync(process.execPath, [path.join(pw, "cli.js"), "test", "--config", path.join(dir, "playwright.config.cjs")],
    { cwd: root, env, encoding: "utf8", windowsHide: true, timeout: 15_000, maxBuffer: 4 * 1024 * 1024 });
  writeFileSync(path.join(dir, "native.json"), result.stdout ?? "");
  writeFileSync(path.join(dir, "stderr.txt"), result.stderr ?? "");
  expect(result.error, dir).toBeUndefined(); expect(result.status, result.stderr + dir).toBe(0);
  const report = JSON.parse(result.stdout);
  expect(report.errors).toEqual([]);
  expect(report.stats).toMatchObject({ expected: 3, unexpected: 0, skipped: 0, flaky: 0 });
}, 20_000);
