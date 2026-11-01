"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const root = process.env.CASEOPS_IP_FIXTURE_SOURCE_ROOT || path.resolve(__dirname, "../../..");
const sourceRequire = createRequire(path.join(root, "apps/web/package.json"));
const ts = sourceRequire("typescript");
const filename = path.join(__dirname, "ip-entitlement-fixture.test.ts");
const nodeTest = require("node:test");
const names = [];
const testRequire = (id) => id === "node:test" ? {
  ...nodeTest,
  test: (...args) => { names.push(args[0]); return nodeTest.test(...args); },
} : sourceRequire(id);
const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText;
// Execute the complete test module, not an AST-extracted subset of the helper.
new Function("require", "module", "exports", "__filename", "__dirname", output)(
  testRequire, module, module.exports, filename, __dirname,
);
if (names.length === 0 || new Set(names).size !== names.length) throw new Error("Empty or duplicate Node test inventory.");
fs.writeFileSync(process.env.CASEOPS_IP_FIXTURE_NODE_INVENTORY, JSON.stringify(names), { flag: "wx" });
