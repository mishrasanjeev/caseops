import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { ALLOWED_LICENSES, buildLicenseReport, licenseDecision } from "./production-js-license-gate.mjs";

const ROOT = path.resolve("license-fixture");
const script = fileURLToPath(new URL("./production-js-license-gate.mjs", import.meta.url));
function fixture() {
  const manifest = { name: "fixture", version: "1.0.0", private: true, workspaces: ["apps/web"], devDependencies: { tooling: "1.0.0" } };
  const web = { name: "@fixture/web", version: "1.0.0", private: true, dependencies: { runtime: "1.0.0" } };
  const runtime = { version: "1.0.0", license: "MIT" };
  const lock = { lockfileVersion: 3, packages: { "": structuredClone(manifest), "apps/web": structuredClone(web),
    "node_modules/@fixture/web": { link: true, resolved: "apps/web" },
    "node_modules/runtime": runtime, "node_modules/tooling": { version: "1.0.0", license: "AGPL-3.0-only", dev: true } } };
  const runtimeNode = { name: "runtime", ...runtime, path: path.join(ROOT, "node_modules/runtime") };
  const webNode = { name: web.name, version: web.version, path: path.join(ROOT, "node_modules/@fixture/web"), dependencies: { runtime: runtimeNode } };
  const lockTree = { name: manifest.name, version: manifest.version, path: ROOT, dependencies: { "@fixture/web": webNode } };
  return { root: ROOT, manifest, workspaces: { "apps/web": web }, lock, lockTree, installedTree: structuredClone(lockTree) };
}
const report = value => buildLicenseReport(value);

test("preserves every existing exact allowlist term, not MIT-0 substring approval", () => {
  assert.deepEqual(ALLOWED_LICENSES, ["MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "PostgreSQL",
    "Python-2.0", "Unlicense", "CC0-1.0", "0BSD", "BlueOak-1.0.0", "CC-BY-4.0", "CC-BY-3.0", "Apache 2.0"]);
  for (const value of ALLOWED_LICENSES) assert.equal(licenseDecision(value).approved, true, value);
  assert.equal(licenseDecision("MIT-0").approved, false);
});
for (const expression of ["(MIT OR CC0-1.0)", "MIT AND Apache-2.0", "MIT OR (BSD-2-Clause AND Apache-2.0)", "((MIT))"]) {
  test(`approves compound only when every explicit term is already approved: ${expression}`, () => {
    assert.equal(licenseDecision(expression).approved, true);
  });
}
for (const expression of ["OFL-1.1", "MIT-0", "Apache-2.0 AND LGPL-3.0-or-later", "MIT AND Zlib",
  "MIT WITH Classpath-exception-2.0", "UNLICENSED", "UNKNOWN",
  "MIT*", "SEE LICENSE IN COPYING", "MIT OR", "MIT AND OR MIT", "MIT AND (ISC", "MIT) OR ISC", "mit", "MIT OR /etc/passwd",
  "(".repeat(33) + "MIT" + ")".repeat(33), "MIT OR ".repeat(300) + "MIT", "M".repeat(2049), "", null, [], { type: "MIT" }]) {
  test(`rejects unapproved, unknown, malformed or bounded license ${JSON.stringify(expression).slice(0, 70)}`, () => {
    assert.equal(licenseDecision(expression).approved, false);
  });
}

for (const [expression, selected, unused] of [
  ["MIT OR GPL-3.0-only", ["MIT"], ["GPL-3.0-only"]],
  ["MIT OR LicenseRef-Unknown", ["MIT"], ["LicenseRef-Unknown"]],
  ["(MIT OR GPL-3.0-or-later)", ["MIT"], ["GPL-3.0-or-later"]],
  ["GPL-3.0-or-later OR MIT", ["MIT"], ["GPL-3.0-or-later"]],
  ["MIT OR (GPL-3.0-or-later AND LGPL-3.0-or-later)", ["MIT"], ["GPL-3.0-or-later", "LGPL-3.0-or-later"]],
  ["(GPL-3.0-or-later AND LGPL-3.0-or-later) OR MIT", ["MIT"], ["GPL-3.0-or-later", "LGPL-3.0-or-later"]],
  ["MIT AND (GPL-3.0-or-later OR Apache-2.0)", ["Apache-2.0", "MIT"], ["GPL-3.0-or-later"]],
  ["(GPL-3.0-or-later OR MIT) AND (LGPL-3.0-or-later OR BSD-3-Clause)", ["BSD-3-Clause", "MIT"], ["GPL-3.0-or-later", "LGPL-3.0-or-later"]],
  ["GPL-3.0-or-later OR MIT AND Apache-2.0", ["Apache-2.0", "MIT"], ["GPL-3.0-or-later"]],
  ["(MIT OR GPL-3.0-or-later) AND (MIT-0 OR ISC)", ["ISC", "MIT"], ["GPL-3.0-or-later", "MIT-0"]],
  ["MIT OR ISC", ["MIT"], []],
  ["ISC OR MIT", ["ISC"], []],
  ["MIT OR (ISC AND MIT)", ["MIT"], []],
  ["MIT WITH Classpath-exception-2.0 OR ISC", ["ISC"], ["MIT WITH Classpath-exception-2.0"]],
  ["ISC OR MIT WITH Classpath-exception-2.0", ["ISC"], ["MIT WITH Classpath-exception-2.0"]],
  ["MIT OR DocumentRef-source:LicenseRef-private", ["MIT"], ["DocumentRef-source:LicenseRef-private"]],
]) {
  test(`elects an approved SPDX alternative without approving unused terms: ${expression}`, () => {
    const value = licenseDecision(expression);
    assert.equal(value.approved, true);
    assert.deepEqual(value.selected_terms, selected);
    assert.deepEqual(value.unapproved_terms, unused);
    assert.deepEqual(value.unused_unapproved_terms, unused);
    assert.equal(value.reason, unused.length ? "approved_spdx_alternative" : "approved_spdx_terms");
  });
}

for (const expression of ["MIT AND GPL-3.0-or-later", "(MIT OR GPL-3.0-or-later) AND Zlib",
  "GPL-3.0-or-later OR LGPL-3.0-or-later", "MIT-0 OR GPL-3.0-or-later",
  "MIT AND Zlib OR MIT-0 AND ISC", "(MIT OR ISC) AND (Zlib OR LGPL-3.0-or-later)"]) {
  test(`AND still requires every selected obligation: ${expression}`, () => {
    const value = licenseDecision(expression);
    assert.equal(value.approved, false);
    assert.deepEqual(value.selected_terms, []);
    assert.deepEqual(value.unused_unapproved_terms, []);
  });
}

const invalidAlternatives = ["(ISC AND)", "GPL-3.0-or-later WITH", "GPL-3.0-or-later AND OR ISC", "(ISC", "ISC)",
  "GPL-3.0-or-later WITH Classpath-exception-2.0 WITH Another", "MIT++", "LicenseRef-", "LicenseRef-x+",
  "DocumentRef-:LicenseRef-x", "((ISC)) WITH Classpath-exception-2.0", "MIT*", "/etc/passwd"];
for (const [index, alternative] of invalidAlternatives.entries()) {
  for (const reverse of [false, true]) {
    test(`validates syntax of both branches before OR choice: ${index} reverse=${reverse}`, () => {
      const expression = reverse ? `${alternative} OR MIT` : `MIT OR ${alternative}`;
      const value = licenseDecision(expression);
      assert.equal(value.approved, false);
      assert.equal(value.reason, "invalid_or_oversized_license_expression");
      assert.deepEqual(value.selected_terms, []);
      assert.deepEqual(value.unused_unapproved_terms, []);
    });
  }
}
for (const [label, alternative] of [
  ["depth", "(".repeat(33) + "GPL-3.0-or-later" + ")".repeat(33)],
  ["tokens", "ISC OR ".repeat(130) + "ISC"],
  ["length", "M".repeat(2049)],
]) {
  for (const reverse of [false, true]) {
    test(`bounds both branches before OR choice: ${label} reverse=${reverse}`, () => {
      const value = licenseDecision(reverse ? `${alternative} OR MIT` : `MIT OR ${alternative}`);
      assert.equal(value.approved, false);
      assert.deepEqual(value.selected_terms, []);
    });
  }
}

test("actual jszip-style inventory elects MIT and retains unused GPL without a policy failure", () => {
  const value = fixture();
  value.lock.packages["node_modules/runtime"].license = "(MIT OR GPL-3.0-or-later)";
  value.lockTree.dependencies["@fixture/web"].dependencies.runtime.license = "(MIT OR GPL-3.0-or-later)";
  value.installedTree = structuredClone(value.lockTree);
  const result = report(value);
  assert.equal(result.exit_code, 0);
  assert.equal(result.inventory_complete, true);
  assert.deepEqual(result.policy_failures, []);
  assert.deepEqual(result.packages[0].decision.selected_terms, ["MIT"]);
  assert.deepEqual(result.packages[0].decision.unused_unapproved_terms, ["GPL-3.0-or-later"]);
});

test("root with only dev dependencies still inventories hoisted private-workspace runtime", () => {
  const value = report(fixture());
  assert.equal(value.exit_code, 0);
  assert.equal(value.inventory_complete, true);
  assert.equal(value.packages.length, 1);
  assert.equal(value.packages[0].id, "runtime@1.0.0");
  assert.equal(value.packages[0].install_status, "installed");
  assert.equal(value.workspaces.length, 2);
});

const corruptions = {
  lockVersion: value => { value.lock.lockfileVersion = 2; },
  empty: value => { delete value.lock.packages["node_modules/runtime"]; value.workspaces["apps/web"].dependencies = {}; value.lock.packages["apps/web"].dependencies = {}; value.lockTree.dependencies["@fixture/web"].dependencies = {}; value.installedTree = structuredClone(value.lockTree); },
  omittedWorkspace: value => { value.lockTree.dependencies = {}; },
  missingWorkspaceManifest: value => { delete value.workspaces["apps/web"]; },
  extraWorkspaceManifest: value => { value.workspaces["apps/extra"] = {}; },
  duplicateWorkspace: value => { value.manifest.workspaces.push("apps/web"); },
  workspaceGlob: value => { value.manifest.workspaces = ["apps/*"]; },
  workspaceTraversal: value => { value.manifest.workspaces = ["../private"]; },
  workspaceLockDrift: value => { value.lock.packages[""].workspaces = []; },
  dependencyLockDrift: value => { value.lock.packages["apps/web"].dependencies.runtime = "2.0.0"; },
  missingDirect: value => { value.lockTree.dependencies["@fixture/web"].dependencies = {}; },
  missingInstalled: value => { value.installedTree.dependencies["@fixture/web"].dependencies = {}; },
  badVersion: value => { value.installedTree.dependencies["@fixture/web"].dependencies.runtime.version = "2.0.0"; },
  badInstalledLicense: value => { value.installedTree.dependencies["@fixture/web"].dependencies.runtime.license = "ISC"; },
  badLockLicense: value => { value.lockTree.dependencies["@fixture/web"].dependencies.runtime.license = "ISC"; },
  nativeProblem: value => { value.lockTree.problems = ["invalid package"]; },
  nativeMissing: value => { value.lockTree.dependencies["@fixture/web"].dependencies.runtime.missing = true; },
  outsidePath: value => { value.lockTree.dependencies["@fixture/web"].path = path.resolve(ROOT, "../elsewhere"); },
  externalLink: value => { value.lock.packages["node_modules/@fixture/web"].resolved = "../elsewhere"; },
  unknownPackage: value => { value.lockTree.dependencies["@fixture/web"].dependencies.runtime.path = path.join(ROOT, "node_modules/not-locked"); },
  devLeak: value => { value.lockTree.dependencies.tooling = { name: "tooling", version: "1.0.0", license: "AGPL-3.0-only", path: path.join(ROOT, "node_modules/tooling") }; },
  npmLockFailed: value => { value.lockExit = 1; },
  npmInstalledFailed: value => { value.installedExit = 1; },
  virtualRootVersion: value => { value.lockTree.version = "2.0.0"; },
  installedRootVersion: value => { value.installedTree.version = "2.0.0"; },
  extraneousRequired: value => { value.installedTree.dependencies["@fixture/web"].dependencies.runtime.extraneous = true; },
};
for (const [name, mutate] of Object.entries(corruptions)) {
  test(`fails incomplete native inventory: ${name}`, () => {
    const value = fixture();
    mutate(value);
    const result = report(value);
    assert.equal(result.exit_code, 2);
    assert.equal(result.inventory_complete, false);
    assert.equal(result.policy_passed, false);
    assert.equal(result.inventory_errors.length, 1);
  });
}

test("missing license is retained with identity and causes policy failure", () => {
  const value = fixture();
  delete value.lock.packages["node_modules/runtime"].license;
  delete value.lockTree.dependencies["@fixture/web"].dependencies.runtime.license;
  delete value.installedTree.dependencies["@fixture/web"].dependencies.runtime.license;
  const result = report(value);
  assert.equal(result.exit_code, 1);
  assert.equal(result.inventory_complete, true);
  assert.deepEqual(result.policy_failures.map(row => [row.id, row.license, row.reason]), [["runtime@1.0.0", null, "missing_or_invalid_license"]]);
});

test("lock-only optional platform packages remain inventoried and policy checked", () => {
  const value = fixture();
  value.lock.packages["node_modules/runtime"].optional = true;
  value.lock.packages["node_modules/runtime"].license = "Apache-2.0 AND LGPL-3.0-or-later";
  value.lockTree.dependencies["@fixture/web"].dependencies.runtime.license = "Apache-2.0 AND LGPL-3.0-or-later";
  value.installedTree.dependencies["@fixture/web"].dependencies = {};
  const result = report(value);
  assert.equal(result.inventory_complete, true);
  assert.equal(result.exit_code, 1);
  assert.equal(result.counts.lock_only_optional, 1);
  assert.equal(result.policy_failures.length, 1);
});

test("lock-backed optional installed extras stay policy checked, exact npm diagnostics retained", () => {
  const value = fixture();
  value.lock.packages["node_modules/runtime"].optional = true;
  value.lock.packages["node_modules/runtime"].license = "MIT-0";
  value.lockTree.dependencies["@fixture/web"].dependencies.runtime.license = "MIT-0";
  value.installedTree = structuredClone(value.lockTree);
  const node = value.installedTree.dependencies["@fixture/web"].dependencies.runtime;
  node.extraneous = true; node.optional = true;
  node.problems = [`extraneous: runtime@1.0.0 ${node.path}`];
  value.installedTree.problems = [...node.problems];
  const result = report(value);
  assert.equal(result.inventory_complete, true);
  assert.equal(result.exit_code, 1);
  assert.equal(result.packages[0].installed_optional_extraneous, true);
});

test("only exact locked dev-only optional extras are excluded from runtime, not hidden", () => {
  const value = fixture();
  value.lock.packages["node_modules/tooling"].optional = true;
  const extra = { name: "tooling", version: "1.0.0", license: "AGPL-3.0-only", optional: true,
    extraneous: true, path: path.join(ROOT, "node_modules/tooling") };
  extra.problems = [`extraneous: tooling@1.0.0 ${extra.path}`];
  value.installedTree.dependencies.tooling = extra;
  value.installedTree.problems = [...extra.problems];
  const result = report(value);
  assert.equal(result.exit_code, 0);
  assert.equal(result.installed_dev_only_extraneous[0].id, "tooling@1.0.0");
  extra.problems.push("missing: another@1.0.0");
  assert.equal(report(value).exit_code, 2);
  extra.problems.pop(); extra.version = "2.0.0";
  assert.equal(report(value).exit_code, 2);
});

for (const reverse of [false, true]) {
  test(`repeated dev-only optional extra/peer classification is traversal independent: ${reverse}`, () => {
    const value = fixture();
    const extra = { name: "tooling", version: "1.0.0", license: "AGPL-3.0-only", optional: true,
      extraneous: true, path: path.join(ROOT, "node_modules/tooling") };
    value.lock.packages["node_modules/tooling"].optional = true;
    value.lock.packages["node_modules/runtime"].peerDependencies = { tooling: "1.0.0" };
    value.lock.packages["node_modules/runtime"].peerDependenciesMeta = { tooling: { optional: true } };
    extra.problems = [`extraneous: tooling@1.0.0 ${extra.path}`];
    value.installedTree.dependencies["@fixture/web"].dependencies.runtime.dependencies = {
      tooling: { ...extra, extraneous: false, problems: [] },
    };
    const entries = [["tooling", extra], ...Object.entries(value.installedTree.dependencies)];
    value.installedTree.dependencies = Object.fromEntries(reverse ? entries.reverse() : entries);
    const result = report(value);
    assert.equal(result.exit_code, 0);
    assert.equal(result.installed_dev_only_extraneous.length, 1);
    assert.equal(result.packages.length, 1);
  });
}

test("a third-party private flag cannot erase a runtime dependency", () => {
  const value = fixture();
  value.lock.packages["node_modules/runtime"].private = true;
  assert.equal(report(value).packages.length, 1);
});

test("only private first-party roots are exempt, public workspace needs approved metadata", () => {
  const value = fixture();
  value.workspaces["apps/web"].private = false;
  value.workspaces["apps/web"].license = "OFL-1.1";
  value.lock.packages["apps/web"].license = "OFL-1.1";
  const result = report(value);
  assert.equal(result.inventory_complete, true);
  assert.equal(result.exit_code, 1);
  assert.equal(result.policy_failures[0].id, "@fixture/web@1.0.0");
});

test("npm aliases retain actual package name and physical lock location", () => {
  const value = fixture();
  value.lock.packages["node_modules/runtime"].name = "underlying";
  value.lockTree.dependencies["@fixture/web"].dependencies.runtime.name = "underlying";
  value.installedTree = structuredClone(value.lockTree);
  const result = report(value);
  assert.equal(result.exit_code, 0);
  assert.equal(result.packages[0].id, "underlying@1.0.0");
  assert.equal(result.packages[0].location, "node_modules/runtime");
});

test("multiple workspaces, root runtime, nested versions and cycles preserve location identity", () => {
  const value = fixture();
  value.manifest.dependencies = { runtime: "1.0.0" };
  value.lock.packages[""].dependencies = { runtime: "1.0.0" };
  value.manifest.workspaces.push("apps/other");
  value.lock.packages[""].workspaces = [...value.manifest.workspaces];
  const source = { name: "@fixture/other", version: "1.0.0", private: true, dependencies: { runtime: "2.0.0" } };
  value.workspaces["apps/other"] = source;
  value.lock.packages["apps/other"] = source;
  value.lock.packages["node_modules/@fixture/other"] = { link: true, resolved: "apps/other" };
  value.lock.packages["apps/other/node_modules/runtime"] = { version: "2.0.0", license: "ISC" };
  const second = { name: "runtime", version: "2.0.0", license: "ISC", path: path.join(ROOT, "apps/other/node_modules/runtime") };
  const first = value.lockTree.dependencies["@fixture/web"].dependencies.runtime;
  value.lock.packages["node_modules/runtime"].dependencies = { runtime: "1.0.0" };
  first.dependencies = { runtime: { ...first, dependencies: {} } };
  value.lockTree.dependencies.runtime = first;
  value.lockTree.dependencies["@fixture/other"] = { name: source.name, version: "1.0.0", path: path.join(ROOT, "node_modules/@fixture/other"), dependencies: { runtime: second } };
  value.installedTree = structuredClone(value.lockTree);
  const result = report(value);
  assert.equal(result.exit_code, 0);
  assert.equal(result.workspaces.length, 3);
  assert.deepEqual(result.packages.map(row => row.id).sort(), ["runtime@1.0.0", "runtime@2.0.0"]);
});

test("runtime peer closure cannot be dropped solely because the lock marks a child dev", () => {
  const value = fixture();
  value.lock.packages["node_modules/runtime"].peerDependencies = { tooling: "1.0.0" };
  value.lockTree.dependencies["@fixture/web"].dependencies.runtime.dependencies = {
    tooling: { name: "tooling", version: "1.0.0", license: "AGPL-3.0-only", path: path.join(ROOT, "node_modules/tooling") },
  };
  value.installedTree = structuredClone(value.lockTree);
  const result = report(value);
  assert.equal(result.inventory_complete, true);
  assert.equal(result.exit_code, 1);
  assert.equal(result.packages.find(row => row.id === "tooling@1.0.0").lock_dev_flag, true);
});

test("conflicting duplicate native location is rejected", () => {
  const value = fixture();
  value.lockTree.dependencies.other = { ...value.lockTree.dependencies["@fixture/web"].dependencies.runtime, version: "2.0.0" };
  assert.equal(report(value).exit_code, 2);
});

test("standard Security gate runs this complete test file and always retains native evidence", () => {
  const workflow = fs.readFileSync(new URL("../.github/workflows/security.yml", import.meta.url), "utf8");
  const job = workflow.split("  license-allowlist:")[1].split("  openapi-client-drift:")[0];
  assert.match(job, /node --test --test-reporter=tap/);
  assert.match(job, /scripts\/production-js-license-gate\.test\.mjs/);
  assert.match(job, /--test-reporter=junit --test-reporter-destination=license-gate-tests\.xml/);
  assert.match(job, /node scripts\/production-js-license-gate\.mjs/);
  assert.match(job, /--package-lock-only/);
  assert.match(job, /--workspaces --include-workspace-root/);
  assert.match(job, /if: always\(\)/);
  assert.match(job, /if-no-files-found: error/);
  assert.doesNotMatch(job, /onlyAllow|excludePrivatePackages|continue-on-error/);
});

test("real CLI writes a complete hashed report before policy failure, preserves prior output", t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "caseops-license-gate-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const value = fixture();
  value.lock.packages["node_modules/runtime"].license = "MIT-0";
  value.lockTree.dependencies["@fixture/web"].dependencies.runtime.license = "MIT-0";
  value.installedTree = structuredClone(value.lockTree);
  function relocate(node) {
    node.path = path.join(directory, path.relative(ROOT, node.path));
    for (const child of Object.values(node.dependencies || {})) relocate(child);
  }
  relocate(value.lockTree); relocate(value.installedTree);
  fs.mkdirSync(path.join(directory, "apps/web"), { recursive: true });
  for (const [name, data] of [["package.json", value.manifest], ["apps/web/package.json", value.workspaces["apps/web"]],
    ["package-lock.json", value.lock], ["lock.json", value.lockTree], ["installed.json", value.installedTree]]) {
    fs.writeFileSync(path.join(directory, name), JSON.stringify(data));
  }
  const output = path.join(directory, "report.json");
  const args = [script, "--root", directory, "--lock-tree", path.join(directory, "lock.json"),
    "--installed-tree", path.join(directory, "installed.json"), "--source-sha", "3dbf364d9834316d181d4a52b2e9b4c7bee431b4", "--output", output];
  const first = spawnSync(process.execPath, args, { encoding: "utf8", timeout: 10_000 });
  assert.equal(first.status, 1, first.stderr);
  const raw = fs.readFileSync(output);
  const result = JSON.parse(raw);
  assert.equal(result.completed, true);
  assert.equal(result.inventory_complete, true);
  assert.equal(result.counts.runtime_locations, 1);
  assert.equal(Object.keys(result.input_sha256).length, 5);
  assert.match(result.script_sha256, /^[a-f0-9]{64}$/);
  assert.equal(spawnSync(process.execPath, args, { timeout: 10_000 }).status, 2);
  assert.deepEqual(fs.readFileSync(output), raw);
});
