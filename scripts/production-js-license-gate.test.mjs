import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { ALLOWED_LICENSES, buildLicenseReport, licenseDecision, readJson } from "./production-js-license-gate.mjs";

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
  const job = assertWorkspaceLockConfiguration(workflow);
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

function workspaceLockJob(workflow) {
  const lines = workflow.replace(/\r\n/g, "\n").split("\n");
  const starts = lines.flatMap((line, index) => /^  license-workspace-lock-policy:\s*$/.test(line) ? [index] : []);
  assert.equal(starts.length, 1, "Exactly one workspace lock policy job is required");
  let end = starts[0] + 1;
  while (end < lines.length && !/^  [A-Za-z0-9_-]+:\s*$/.test(lines[end])) end += 1;
  return lines.slice(starts[0], end).filter(line => !line.trimStart().startsWith("#")).join("\n");
}

function assertWorkspaceLockConfiguration(workflow) {
  const job = workspaceLockJob(workflow);
  for (const marker of ["node --test --test-reporter=tap", "scripts/production-js-license-gate.test.mjs",
    "--test-reporter=junit --test-reporter-destination=license-gate-tests.xml",
    "node scripts/production-js-license-gate.mjs", "--package-lock-only", "--workspaces --include-workspace-root",
    '--review-root "$GITHUB_WORKSPACE"']) assert.ok(job.includes(marker), `Missing target marker: ${marker}`);
  assert.doesNotMatch(job, /onlyAllow|excludePrivatePackages|continue-on-error|--test-name-pattern|\|\|\s*true/);
  assert.doesNotMatch(job, /^    (?:needs:|if:\s*success\()/m);
  const steps = job.split(/(?=^      - )/m);
  const uploads = steps.filter(step => step.includes("- uses: actions/upload-artifact@v4"));
  assert.equal(uploads.length, 1, "One target evidence upload is required");
  const upload = uploads[0];
  assert.match(upload, /^        if: always\(\)\s*$/m);
  assert.match(upload, /^          name: js-license-workspace-lock-report\s*$/m);
  assert.match(upload, /^          if-no-files-found: error\s*$/m);
  for (const file of ["license-report.json", "license-lock-tree.json", "license-lock-tree.stderr",
    "license-installed-tree.json", "license-installed-tree.stderr", "license-gate-tests.tap", "license-gate-tests.xml"]) {
    assert.ok(upload.split("\n").some(line => line.trim() === file), `Missing retained target receipt: ${file}`);
  }
  return job;
}

function wiringFixture(terminal = false) {
  const body = `    steps:
      - run: |
          node --test --test-reporter=tap --test-reporter-destination=license-gate-tests.tap \\
            --test-reporter=junit --test-reporter-destination=license-gate-tests.xml \\
            scripts/production-js-license-gate.test.mjs
          npm ls --package-lock-only --omit=dev --all --long --json --workspaces --include-workspace-root
          node scripts/production-js-license-gate.mjs --review-root "$GITHUB_WORKSPACE"
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: js-license-workspace-lock-report
          if-no-files-found: error
          path: |
            license-report.json
            license-lock-tree.json
            license-lock-tree.stderr
            license-installed-tree.json
            license-installed-tree.stderr
            license-gate-tests.tap
            license-gate-tests.xml
`;
  return `jobs:
  python-sibling:
${body}      - run: license-checker --onlyAllow unchanged
  license-workspace-lock-policy:
${body}${terminal ? "" : `  later-sibling:\n${body}      - run: license-checker --onlyAllow unchanged\n`}`;
}

function mutateTarget(workflow, before, after) {
  const job = workspaceLockJob(workflow);
  assert.ok(job.includes(before), "Mutation must change the actual target");
  return workflow.replace(job, job.replace(before, after));
}

test("WLP-01 missing target rejects despite complete sibling markers", () => {
  assert.throws(() => assertWorkspaceLockConfiguration(wiringFixture().replace("  license-workspace-lock-policy:", "  renamed-policy:")));
});
test("WLP-02 duplicate target keys reject rather than selecting a sibling", () => {
  const text = wiringFixture();
  assert.throws(() => assertWorkspaceLockConfiguration(text + "\n" + workspaceLockJob(text)));
});
test("WLP-03 sibling gate command cannot satisfy a missing target command", () => {
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), "node scripts/production-js-license-gate.mjs", "echo removed")));
});
test("WLP-04 target needs the entire native file without a name filter", () => {
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), "scripts/production-js-license-gate.test.mjs", "other.test.mjs")));
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), "node --test", "node --test --test-name-pattern=one")));
});
test("WLP-05 target has distinct artifact identity and every raw receipt", () => {
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), "name: js-license-workspace-lock-report", "name: js-license-report")));
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), "            license-installed-tree.stderr", "            omitted.stderr")));
});
test("WLP-06 sibling always-upload cannot satisfy missing target retention", () => {
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), "if: always()", "if: success()")));
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), "if-no-files-found: error", "if-no-files-found: ignore")));
});
test("WLP-07 target strict failures stay independent and unswallowed", () => {
  for (const marker of ["    needs: license-allowlist\n", "    if: success()\n", "    continue-on-error: true\n"]) {
    assert.throws(() => assertWorkspaceLockConfiguration(wiringFixture().replace("  license-workspace-lock-policy:\n", "  license-workspace-lock-policy:\n" + marker)));
  }
  assert.throws(() => assertWorkspaceLockConfiguration(mutateTarget(wiringFixture(), ' --review-root "$GITHUB_WORKSPACE"', ' --review-root "$GITHUB_WORKSPACE" || true')));
});
test("WLP-08 target ends at the next job or EOF without sibling onlyAllow", () => {
  assertWorkspaceLockConfiguration(wiringFixture());
  assertWorkspaceLockConfiguration(wiringFixture(true));
  assert.doesNotMatch(workspaceLockJob(wiringFixture()), /later-sibling|onlyAllow/);
});

function fakeReviewFixture(t, license = "OFL-1.1") {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "caseops-fake-license-review-"));
  t.after(() => { t.mock.restoreAll(); fs.rmSync(directory, { recursive: true, force: true }); });
  const value = fixture();
  value.reviewRoot = directory;
  value.lock.packages["node_modules/runtime"].license = license;
  value.lock.packages["node_modules/runtime"].integrity = "sha512-" + Buffer.alloc(64, 7).toString("base64");
  value.lockTree.dependencies["@fixture/web"].dependencies.runtime.license = license;
  value.installedTree = structuredClone(value.lockTree);
  const write = (relative, contents) => {
    const file = path.join(directory, relative);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, contents);
    return createHash("sha256").update(fs.readFileSync(file)).digest("hex");
  };
  const document = "docs/security/js-license-compliance-review-2026-10-12.md";
  const licenseFile = "license-policy/materials/fake-runtime-LICENSE.txt";
  const notice = "apps/web/public/third-party-notices/fake-runtime-NOTICE.txt";
  const review = { schema_version: 1, scope: "managed-saas-only",
    review_document: { path: document, sha256: write(document, "FAKE UNIT REVIEW ONLY\r\nNo actual license approval.\r\n") },
    packages: [{ name: "runtime", version: "1.0.0", license, integrity: value.lock.packages["node_modules/runtime"].integrity,
      materials: [{ path: licenseFile, sha256: write(licenseFile, "FAKE UNIT LICENSE ONLY\r\n") },
        { path: notice, sha256: write(notice, "FAKE UNIT NOTICE ONLY\r\n") }] }] };
  const save = () => {
    fs.mkdirSync(path.join(directory, "license-policy"), { recursive: true });
    fs.writeFileSync(path.join(directory, "license-policy/reviewed-packages.json"), JSON.stringify(review));
  };
  save();
  return { directory, value, review, save, write, document, notice, licenseFile };
}

test("MAT-01 exact fake reviewed package is admitted without changing base terms or hiding inventory", t => {
  const value = fakeReviewFixture(t);
  const result = report(value.value);
  assert.equal(licenseDecision("OFL-1.1").approved, false);
  assert.equal(result.exit_code, 0);
  assert.equal(result.packages.length, 1);
  assert.equal(result.packages[0].id, "runtime@1.0.0");
  assert.equal(result.packages[0].review_admission.scope, "managed-saas-only");
  assert.equal(result.packages[0].review_admission.integrity, value.review.packages[0].integrity);
});
for (const field of ["name", "version", "license", "integrity"]) {
  test(`MAT exact review cannot admit a changed ${field}`, t => {
    const value = fakeReviewFixture(t);
    value.review.packages[0][field] = field === "integrity"
      ? "sha512-" + Buffer.alloc(64, 8).toString("base64") : value.review.packages[0][field] + "-changed";
    value.save();
    const result = report(value.value);
    assert.equal(result.exit_code, 1);
    assert.equal(result.packages.length, 1);
    assert.equal(result.policy_failures.length, 1);
  });
}
test("MAT-02 missing review leaves original unsupported metadata red", t => {
  const value = fakeReviewFixture(t);
  fs.unlinkSync(path.join(value.directory, "license-policy/reviewed-packages.json"));
  assert.equal(report(value.value).exit_code, 1);
});
test("MAT-03 scanner integrity cannot replace the exact lock integrity", t => {
  const value = fakeReviewFixture(t);
  delete value.value.lock.packages["node_modules/runtime"].integrity;
  value.value.installedTree.dependencies["@fixture/web"].dependencies.runtime.integrity = value.review.packages[0].integrity;
  assert.equal(report(value.value).exit_code, 1);
});
for (const label of ["review document", "license material", "notice material"]) {
  test(`MAT missing ${label} blocks and retains visible package inventory`, t => {
    const value = fakeReviewFixture(t);
    const relative = label === "review document" ? value.document : label === "license material" ? value.licenseFile : value.notice;
    fs.unlinkSync(path.join(value.directory, relative));
    const result = report(value.value);
    assert.equal(result.exit_code, 2);
    assert.equal(result.packages.length, 1);
  });
}
test("MAT-04 original material bytes, including CRLF, cannot be normalized for admission", t => {
  const value = fakeReviewFixture(t);
  const file = path.join(value.directory, value.notice);
  fs.writeFileSync(file, fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n"));
  const result = report(value.value);
  assert.equal(result.exit_code, 2);
  assert.equal(result.packages.length, 1);
});
test("MAT-05 repeated calls revalidate material changes instead of borrowing cached approval", t => {
  const value = fakeReviewFixture(t);
  assert.equal(report(value.value).exit_code, 0);
  value.write(value.notice, "CHANGED FAKE NOTICE\n");
  assert.equal(report(value.value).exit_code, 2);
});
test("MAT-06 unreviewed duplicate lock identity stays visible and blocked", t => {
  const value = fakeReviewFixture(t);
  const nested = "node_modules/runtime/node_modules/other";
  value.value.lock.packages["node_modules/runtime"].dependencies = { other: "1.0.0" };
  value.value.lock.packages[nested] = { version: "1.0.0", license: "OFL-1.1", integrity: value.review.packages[0].integrity };
  value.value.lockTree.dependencies["@fixture/web"].dependencies.runtime.dependencies = {
    other: { name: "other", version: "1.0.0", license: "OFL-1.1", path: path.join(ROOT, nested) },
  };
  value.value.installedTree = structuredClone(value.value.lockTree);
  const result = report(value.value);
  assert.equal(result.exit_code, 1);
  assert.equal(result.packages.length, 2);
  assert.deepEqual(result.policy_failures.map(row => row.id), ["other@1.0.0"]);
});

const reviewCorruptions = {
  schema: value => { value.review.schema_version = 2; },
  scope: value => { value.review.scope = "all-distributions"; },
  extraRootField: value => { value.review.approved = true; },
  extraEntryField: value => { value.review.packages[0].approved = true; },
  duplicateIds: value => { value.review.packages.push(structuredClone(value.review.packages[0])); },
  missingDocument: value => { delete value.review.review_document; },
  documentHash: value => { value.review.review_document.sha256 = "a".repeat(64); },
  uppercaseHash: value => { value.review.review_document.sha256 = value.review.review_document.sha256.toUpperCase(); },
  emptyMaterials: value => { value.review.packages[0].materials = []; },
  invalidMaterialHash: value => { value.review.packages[0].materials[0].sha256 = "0".repeat(63); },
  badMaterialHash: value => { value.review.packages[0].materials[0].sha256 = "0".repeat(64); },
  extraMaterialField: value => { value.review.packages[0].materials[0].approved = true; },
  entryLimit: value => { value.review.packages = Array.from({ length: 33 }, (_, index) => ({ ...value.review.packages[0], name: `fake-${index}` })); },
  perEntryMaterialLimit: value => { value.review.packages[0].materials = Array.from({ length: 33 }, (_, index) => ({ path: `license-policy/fake-${index}.txt`, sha256: "0".repeat(64) })); },
  globalMaterialLimit: value => { value.review.packages = Array.from({ length: 3 }, (_, group) => ({ ...value.review.packages[0], name: `fake-${group}`, materials: Array.from({ length: group === 2 ? 1 : 32 }, (_, index) => ({ path: `license-policy/fake-${group}-${index}.txt`, sha256: "0".repeat(64) })) })); },
};
for (const [name, mutate] of Object.entries(reviewCorruptions)) {
  test(`MAT schema/material bound fails closed: ${name}`, t => {
    const value = fakeReviewFixture(t, "MIT");
    mutate(value); value.save();
    const result = report(value.value);
    assert.equal(result.exit_code, 2);
    assert.equal(result.packages.length, 1);
    assert.equal(result.inventory_complete, false);
  });
}
for (const relative of [".env", "private/customer.txt", "../private.txt", "/etc/passwd", "C:/private.txt",
  "license-policy/../.env", "license-policy\\private.txt", "license-policy/secret:stream", "license-policy/.env",
  "apps/web/public/third-party-notices/../../private.txt", "docs/another-review.md"]) {
  test(`MAT private/unsafe material path is rejected before opening: ${relative}`, t => {
    const value = fakeReviewFixture(t, "MIT");
    value.review.packages[0].materials[0].path = relative; value.save();
    const open = fs.openSync, opened = [];
    t.mock.method(fs, "openSync", (file, ...args) => { opened.push(String(file)); return open(file, ...args); });
    const result = report(value.value);
    assert.equal(result.exit_code, 2);
    assert.equal(opened.some(file => file.endsWith(relative)), false);
  });
}
test("MAT registry 128KiB bound rejects before an oversized allocation", t => {
  const value = fakeReviewFixture(t, "MIT");
  fs.truncateSync(path.join(value.directory, "license-policy/reviewed-packages.json"), 128 * 1024 + 1);
  const allocate = Buffer.allocUnsafe, sizes = [];
  t.mock.method(Buffer, "allocUnsafe", size => { sizes.push(size); return allocate(size); });
  assert.equal(report(value.value).exit_code, 2);
  assert.ok(sizes.every(size => size <= 128 * 1024 + 1));
});
test("MAT material 1MiB bound rejects without reading oversized content", t => {
  const value = fakeReviewFixture(t, "MIT");
  fs.truncateSync(path.join(value.directory, value.notice), 1024 * 1024 + 1);
  assert.equal(report(value.value).exit_code, 2);
});
test("MAT shared material digest conflicts cannot borrow another entry's review", t => {
  const value = fakeReviewFixture(t, "MIT");
  const second = structuredClone(value.review.packages[0]);
  second.name = "other"; second.materials[0].sha256 = "0".repeat(64);
  value.review.packages.push(second); value.save();
  assert.equal(report(value.value).exit_code, 2);
});
test("MAT a real directory reparse point cannot redirect material reads", t => {
  const value = fakeReviewFixture(t, "MIT");
  const outside = path.join(value.directory, "outside"); fs.mkdirSync(outside);
  fs.writeFileSync(path.join(outside, "private.txt"), "FAKE PRIVATE UNIT BYTES");
  const alias = path.join(value.directory, "license-policy/alias");
  fs.symlinkSync(outside, alias, process.platform === "win32" ? "junction" : "dir");
  value.review.packages[0].materials[0].path = "license-policy/alias/private.txt"; value.save();
  const result = report(value.value);
  assert.equal(result.exit_code, 2);
  assert.equal(result.packages.length, 1);
});

test("MAT exact 64-reference bound includes document with 32 entries and 32 materials per entry", t => {
  const value = fakeReviewFixture(t);
  const materials = Array.from({ length: 63 }, (_, index) => {
    const relative = `license-policy/fake-${index}.txt`;
    return { path: relative, sha256: value.write(relative, "FAKE BOUNDARY MATERIAL ONLY\n") };
  });
  value.review.packages = Array.from({ length: 32 }, (_, index) => ({ ...value.review.packages[0],
    name: index === 0 ? "runtime" : `fake-${index}`, materials: index % 2 === 0 ? materials.slice(0, 32)
      : [...materials.slice(32), value.review.review_document] }));
  value.save();
  value.value.reviewHashes = {};
  assert.equal(report(value.value).exit_code, 0);
  assert.equal(Object.keys(value.value.reviewHashes).length, 65); // Registry plus exactly 64 unique references.
});

test("MAT material reader uses one bounded descriptor, never path-based content reads", t => {
  const value = fakeReviewFixture(t), open = fs.openSync, read = fs.readSync, close = fs.closeSync;
  const descriptors = [], reads = [], closes = [];
  t.mock.method(fs, "readFileSync", () => { throw new Error("path_content_read_forbidden"); });
  t.mock.method(fs, "openSync", (file, ...args) => { const descriptor = open(file, ...args); descriptors.push(descriptor); return descriptor; });
  t.mock.method(fs, "readSync", (descriptor, buffer, offset, length, position) => {
    reads.push(descriptor); assert.ok(length <= 64 * 1024);
    return read(descriptor, buffer, offset, Math.min(length, 1), position);
  });
  t.mock.method(fs, "closeSync", descriptor => { closes.push(descriptor); return close(descriptor); });
  assert.equal(report(value.value).exit_code, 0);
  assert.equal(descriptors.length, 4);
  assert.ok(reads.length > 4 && reads.every(descriptor => descriptors.includes(descriptor)));
  assert.deepEqual(closes, descriptors);
});

for (const operation of ["growth", "truncation", "same-size rewrite", "changed leaf identity", "read failure", "close failure"]) {
  test(`MAT descriptor mutation rejects and closes: ${operation}`, t => {
    const value = fakeReviewFixture(t, "MIT"), target = path.join(value.directory, value.notice);
    const open = fs.openSync, read = fs.readSync, close = fs.closeSync, lstat = fs.lstatSync;
    let descriptor, closed = false, changed = false;
    t.mock.method(fs, "openSync", (file, ...args) => {
      const fd = open(file, ...args); if (file === target) descriptor = fd; return fd;
    });
    t.mock.method(fs, "lstatSync", (file, options) => {
      const stat = lstat(file, options);
      return file === target && descriptor !== undefined && operation === "changed leaf identity"
        ? Object.assign(Object.create(stat), { ino: stat.ino + 1n }) : stat;
    });
    t.mock.method(fs, "readSync", (fd, ...args) => {
      if (fd === descriptor && !changed) {
        changed = true;
        if (operation === "growth") fs.appendFileSync(target, "x");
        if (operation === "truncation") fs.truncateSync(target, 1);
        if (operation === "same-size rewrite") { fs.writeFileSync(target, "x".repeat(Number(lstat(target).size))); fs.utimesSync(target, new Date(0), new Date(1_000)); }
        if (operation === "read failure") throw new Error("fake_material_io_error");
      }
      return read(fd, ...args);
    });
    t.mock.method(fs, "closeSync", fd => {
      close(fd);
      if (fd === descriptor) { closed = true; if (operation === "close failure") throw new Error("fake_material_close_error"); }
    });
    const result = report(value.value);
    assert.equal(result.exit_code, 2);
    assert.equal(result.packages.length, 1);
    assert.equal(closed, true);
  });
}

test("MAT review document private path rejects before any material content opens", t => {
  const value = fakeReviewFixture(t, "MIT"), open = fs.openSync, opened = [];
  value.review.review_document.path = ".env"; value.save();
  t.mock.method(fs, "openSync", (file, ...args) => { opened.push(String(file)); return open(file, ...args); });
  assert.equal(report(value.value).exit_code, 2);
  assert.deepEqual(opened, [path.join(value.directory, "license-policy/reviewed-packages.json")]);
});

test("MAT registry duplicate JSON fields fail closed rather than last-key admission", t => {
  const value = fakeReviewFixture(t, "MIT");
  const raw = JSON.stringify(value.review).replace('"schema_version":1', '"schema_version":2,"schema_version":1');
  fs.writeFileSync(path.join(value.directory, "license-policy/reviewed-packages.json"), raw);
  assert.equal(report(value.value).exit_code, 2);
});

test("MAT disappearing registry after open is invalid, not an absent-review fallback", t => {
  const value = fakeReviewFixture(t, "MIT"), open = fs.openSync;
  const target = path.join(value.directory, "license-policy/reviewed-packages.json");
  t.mock.method(fs, "openSync", (file, ...args) => {
    const descriptor = open(file, ...args);
    if (file === target) fs.renameSync(target, target + ".removed");
    return descriptor;
  });
  assert.equal(report(value.value).exit_code, 2);
});

test("MAT exact byte limits accept 128KiB registry and 1MiB material", t => {
  const value = fakeReviewFixture(t);
  value.review.packages[0].materials[0].sha256 = value.write(value.licenseFile, Buffer.alloc(1024 * 1024, "F"));
  const raw = JSON.stringify(value.review);
  fs.writeFileSync(path.join(value.directory, "license-policy/reviewed-packages.json"), raw + " ".repeat(128 * 1024 - Buffer.byteLength(raw)));
  assert.equal(report(value.value).exit_code, 0);
});

test("MAT real CLI review-root is independent, exact, hashed and never globally approving", t => {
  const value = fakeReviewFixture(t), root = path.join(value.directory, "fake-native-root");
  function relocate(node) {
    node.path = path.join(root, path.relative(ROOT, node.path));
    for (const child of Object.values(node.dependencies || {})) relocate(child);
  }
  relocate(value.value.lockTree); relocate(value.value.installedTree);
  fs.mkdirSync(path.join(root, "apps/web"), { recursive: true });
  const inputs = [["package.json", value.value.manifest], ["package-lock.json", value.value.lock],
    ["apps/web/package.json", value.value.workspaces["apps/web"]], ["lock.json", value.value.lockTree],
    ["installed.json", value.value.installedTree]];
  for (const [relative, data] of inputs) fs.writeFileSync(path.join(root, relative), JSON.stringify(data));
  const args = [script, "--root", root, "--lock-tree", path.join(root, "lock.json"), "--installed-tree", path.join(root, "installed.json"),
    "--source-sha", "3dbf364d9834316d181d4a52b2e9b4c7bee431b4", "--review-root", value.directory];
  const invoke = (filename, arguments_) => {
    const output = path.join(root, filename);
    const result = spawnSync(process.execPath, [...arguments_, "--output", output], { encoding: "utf8", timeout: 10_000 });
    return { result, report: JSON.parse(fs.readFileSync(output)) };
  };
  const first = invoke("reviewed.json", args);
  assert.equal(first.result.status, 0, first.result.stderr);
  assert.equal(Object.keys(first.report.input_sha256).length, 9);
  assert.equal(first.report.input_sha256[value.notice], value.review.packages[0].materials[1].sha256);
  assert.deepEqual(first.report.allowed_licenses, ALLOWED_LICENSES);
  const missing = invoke("missing-review.json", args.slice(0, -2));
  assert.equal(missing.result.status, 1, missing.result.stderr);
  value.value.lock.packages["node_modules/runtime"].integrity += "-changed";
  fs.writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(value.value.lock));
  const changed = invoke("changed-lock.json", args);
  assert.equal(changed.result.status, 1, changed.result.stderr);
  assert.equal(changed.report.packages.length, 1);
  assert.equal(changed.report.packages[0].review_admission, undefined);
});

test("MAT supplied review-root junction rejects before root resolution or content open", t => {
  const value = fakeReviewFixture(t, "MIT"), alias = path.join(value.directory, "fake-root-alias");
  fs.symlinkSync(value.directory, alias, process.platform === "win32" ? "junction" : "dir");
  value.value.reviewRoot = alias;
  const resolve = path.resolve, open = fs.openSync, resolved = [], opened = [];
  t.mock.method(path, "resolve", (...args) => { resolved.push(...args); return resolve(...args); });
  t.mock.method(fs, "openSync", (file, ...args) => { opened.push(file); return open(file, ...args); });
  const result = report(value.value);
  assert.equal(result.exit_code, 2);
  assert.equal(result.packages.length, 1);
  assert.equal(resolved.includes(alias), false);
  assert.deepEqual(opened, []);
});

test("MAT exact compliance document cannot be replaced by a correctly hashed public notice", t => {
  const value = fakeReviewFixture(t, "MIT"), open = fs.openSync, opened = [];
  value.review.review_document = structuredClone(value.review.packages[0].materials[1]); value.save();
  t.mock.method(fs, "openSync", (file, ...args) => { opened.push(file); return open(file, ...args); });
  const result = report(value.value);
  assert.equal(result.exit_code, 2);
  assert.equal(result.packages.length, 1);
  assert.deepEqual(opened, [path.join(value.directory, "license-policy/reviewed-packages.json")]);
});

function invalidContractBeforeMaterialRead(t, value, reason) {
  value.save();
  const open = fs.openSync, opened = [];
  t.mock.method(fs, "openSync", (file, ...args) => { opened.push(String(file)); return open(file, ...args); });
  try {
    const result = report(value.value);
    assert.equal(result.exit_code, 2);
    assert.equal(result.inventory_complete, false);
    assert.equal(result.packages.length, 1);
    assert.ok(result.inventory_errors.some(error => error === `review_registry_invalid:${reason}`), JSON.stringify(result.inventory_errors));
    assert.deepEqual(opened, [path.join(value.directory, "license-policy/reviewed-packages.json")]);
  } finally { t.mock.restoreAll(); }
}

test("CONTRACT zero package entries reject before any material content", t => {
  const value = fakeReviewFixture(t, "MIT");
  value.review.packages = [];
  invalidContractBeforeMaterialRead(t, value, "review_entry_bound");
});

for (const [field, maximum] of [["name", 214], ["version", 128], ["license", 2048], ["integrity", 512]]) {
  test(`CONTRACT ${field} over ${maximum} characters rejects before material content`, t => {
    const value = fakeReviewFixture(t, "MIT");
    value.review.packages[0][field] = "x".repeat(maximum + 1);
    invalidContractBeforeMaterialRead(t, value, "review_identity_shape");
  });
  test(`CONTRACT ${field} control characters reject before material content`, t => {
    for (const character of ["\x00", "\n", "\x7f", "\u0085"]) {
      const value = fakeReviewFixture(t, "MIT");
      value.review.packages[0][field] += character;
      invalidContractBeforeMaterialRead(t, value, "review_identity_shape");
    }
  });
}

test("CONTRACT exact name version license character bounds accept with valid SHA512 integrity", t => {
  const value = fakeReviewFixture(t, "MIT");
  const entry = value.review.packages[0];
  entry.name = "n".repeat(214); entry.version = "v".repeat(128); entry.license = "L".repeat(2048);
  value.save();
  assert.equal(report(value.value).exit_code, 0);
});

test("CONTRACT field character limits count Unicode code points like Python", t => {
  const value = fakeReviewFixture(t, "MIT");
  const entry = value.review.packages[0];
  entry.name = "\u{1f600}".repeat(214); entry.version = "\u{1f600}".repeat(128); entry.license = "\u{1f600}".repeat(2048);
  value.save();
  assert.equal(report(value.value).exit_code, 0);
});

const canonicalFakeIntegrity = "sha512-" + Buffer.alloc(64, 7).toString("base64");
for (const [name, integrity] of [
  ["wrong algorithm", canonicalFakeIntegrity.replace("sha512-", "sha256-")],
  ["wrong algorithm case", canonicalFakeIntegrity.replace("sha512-", "SHA512-")],
  ["non-base64 character", canonicalFakeIntegrity.replace("B", "!")],
  ["base64url character", canonicalFakeIntegrity.replace("B", "_")],
  ["embedded whitespace", canonicalFakeIntegrity.slice(0, 12) + " " + canonicalFakeIntegrity.slice(12)],
  ["missing padding", canonicalFakeIntegrity.slice(0, -2)],
  ["excess padding", canonicalFakeIntegrity + "="],
  ["noncanonical padding bits", canonicalFakeIntegrity.slice(0, -3) + "x=="],
  ["trailing payload", canonicalFakeIntegrity + "AAAA"],
  ["63 decoded bytes", "sha512-" + Buffer.alloc(63, 7).toString("base64")],
  ["65 decoded bytes", "sha512-" + Buffer.alloc(65, 7).toString("base64")],
  ["multiple SRI hashes", canonicalFakeIntegrity + " " + canonicalFakeIntegrity],
]) {
  test(`CONTRACT invalid SHA512 SRI rejects before material content: ${name}`, t => {
    const value = fakeReviewFixture(t, "MIT");
    value.review.packages[0].integrity = integrity;
    value.value.lock.packages["node_modules/runtime"].integrity = integrity;
    invalidContractBeforeMaterialRead(t, value, "review_integrity_shape");
  });
}

test("CONTRACT duplicate materials within one entry reject before content with valid hashes", t => {
  const value = fakeReviewFixture(t, "MIT");
  value.review.packages[0].materials.push(structuredClone(value.review.packages[0].materials[0]));
  invalidContractBeforeMaterialRead(t, value, "review_duplicate_material");
});

test("CONTRACT exact 65-reference inventory rejects before content, every material hash valid", t => {
  const value = fakeReviewFixture(t, "MIT");
  const materials = Array.from({ length: 64 }, (_, index) => {
    const relative = `license-policy/fake-reference-${index}.txt`;
    return { path: relative, sha256: value.write(relative, "FAKE CONTRACT BOUNDARY MATERIAL ONLY\n") };
  });
  value.review.packages = Array.from({ length: 2 }, (_, index) => ({ ...value.review.packages[0],
    name: index === 0 ? "runtime" : "fake-other", materials: materials.slice(index * 32, index * 32 + 32) }));
  assert.equal(new Set([value.review.review_document.path, ...materials.map(value => value.path)]).size, 65);
  assert.ok(materials.every(value => value.sha256 !== "0".repeat(64)));
  invalidContractBeforeMaterialRead(t, value, "review_global_material_bound");
});

test("MAT actual parent junction replacement before open rejects with zero content reads", t => {
  const value = fakeReviewFixture(t, "MIT"), target = path.join(value.directory, value.licenseFile);
  const parent = path.dirname(target), saved = parent + "-original", replacement = path.join(value.directory, "fake-replacement-parent");
  fs.mkdirSync(replacement);
  fs.writeFileSync(path.join(replacement, path.basename(target)), "FAKE UNREVIEWED TARGET ONLY\n");
  const open = fs.openSync, read = fs.readSync, close = fs.closeSync;
  let replaced = false, descriptor, closed = false, contentReads = 0;
  t.mock.method(fs, "openSync", (file, ...args) => {
    if (file === target && !replaced) {
      fs.renameSync(parent, saved);
      fs.symlinkSync(replacement, parent, process.platform === "win32" ? "junction" : "dir");
      replaced = true;
    }
    const fd = open(file, ...args);
    if (file === target) descriptor = fd;
    return fd;
  });
  t.mock.method(fs, "readSync", (fd, ...args) => {
    if (replaced && fd === descriptor) contentReads++;
    return read(fd, ...args);
  });
  t.mock.method(fs, "closeSync", fd => { if (replaced && fd === descriptor) closed = true; return close(fd); });
  const result = report(value.value);
  assert.equal(result.exit_code, 2);
  assert.equal(result.packages.length, 1);
  assert.equal(replaced, true);
  assert.equal(closed, true);
  assert.equal(contentReads, 0);
});

test("JSON native Windows zero-device leaf binds by inode without accepting a wrong nonzero device", t => {
  const value = jsonInputFixture(t), lstat = fs.lstatSync, fstat = fs.fstatSync;
  const descriptor = fs.openSync(value.filename, "r");
  let metadata;
  try { metadata = fstat(descriptor, { bigint: true }); }
  finally { fs.closeSync(descriptor); }
  // Use the same native descriptor checks on both platforms, without mocking inode identity.
  t.mock.method(fs, "lstatSync", (file, options) => Object.assign(Object.create(lstat(file, options)), { dev: metadata.dev + 1n }));
  assert.throws(() => readJson(value.filename, value.hashes, "input"), /json_input_path_identity_changed/);
  t.mock.restoreAll();
  assert.deepEqual(readJson(value.filename, value.hashes, "input"), {});
});

function jsonInputFixture(t, contents = "{}") {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "caseops-license-input-"));
  const filename = path.join(directory, "input.json");
  fs.writeFileSync(filename, contents);
  t.after(() => { t.mock.restoreAll(); fs.rmSync(directory, { recursive: true, force: true }); });
  return { directory, filename, hashes: {} };
}

test("JSON opens once and checks/reads/closes that descriptor, never a path-based read", t => {
  const value = jsonInputFixture(t);
  const open = fs.openSync, read = fs.readSync, close = fs.closeSync;
  const descriptors = [], reads = [], closes = [];
  t.mock.method(fs, "statSync", () => { throw new Error("path_stat_forbidden"); });
  t.mock.method(fs, "readFileSync", () => { throw new Error("path_read_forbidden"); });
  t.mock.method(fs, "openSync", (file, flags) => {
    assert.equal(file, value.filename);
    if (fs.constants.O_NOFOLLOW) assert.ok(flags & fs.constants.O_NOFOLLOW);
    if (fs.constants.O_NONBLOCK) assert.ok(flags & fs.constants.O_NONBLOCK);
    const descriptor = open(file, flags); descriptors.push(descriptor); return descriptor;
  });
  t.mock.method(fs, "readSync", (descriptor, ...args) => { reads.push(descriptor); return read(descriptor, ...args); });
  t.mock.method(fs, "closeSync", descriptor => { closes.push(descriptor); return close(descriptor); });
  assert.deepEqual(readJson(value.filename, value.hashes, "input"), {});
  assert.equal(descriptors.length, 1);
  assert.ok(reads.length > 0 && reads.every(descriptor => descriptor === descriptors[0]));
  assert.deepEqual(closes, descriptors);
  assert.match(value.hashes.input, /^[a-f0-9]{64}$/);
});

test("JSON rejects an oversized descriptor before buffer allocation or reading", t => {
  const value = jsonInputFixture(t);
  fs.truncateSync(value.filename, 16 * 1024 * 1024 + 1);
  const allocation = t.mock.method(Buffer, "allocUnsafe", () => { throw new Error("allocation_forbidden"); });
  const read = t.mock.method(fs, "readSync", () => { throw new Error("read_forbidden"); });
  assert.throws(() => readJson(value.filename, value.hashes, "input"), /oversized_json_input/);
  assert.equal(allocation.mock.callCount(), 0);
  assert.equal(read.mock.callCount(), 0);
  assert.deepEqual(value.hashes, {});
});

test("JSON accepts exactly 16MiB with at most size plus one bounded buffer", t => {
  const body = Buffer.alloc(16 * 1024 * 1024, " "); body.write("{}");
  const value = jsonInputFixture(t, body), allocate = Buffer.allocUnsafe, read = fs.readSync;
  const allocations = [], requested = [];
  t.mock.method(Buffer, "allocUnsafe", size => { allocations.push(size); return allocate(size); });
  t.mock.method(fs, "readSync", (descriptor, buffer, offset, length, position) => {
    requested.push(length); return read(descriptor, buffer, offset, length, position);
  });
  assert.deepEqual(readJson(value.filename, value.hashes, "input"), {});
  assert.deepEqual(allocations, [16 * 1024 * 1024 + 1]);
  assert.ok(requested.every(length => length <= 64 * 1024));
});

test("JSON growth after fstat cannot turn a small allocation into an unbounded read", t => {
  const value = jsonInputFixture(t), stat = fs.fstatSync, read = fs.readSync, allocate = Buffer.allocUnsafe;
  const allocations = [], requested = []; let mutated = false;
  t.mock.method(fs, "fstatSync", (descriptor, options) => {
    const result = stat(descriptor, options);
    if (!mutated) { mutated = true; fs.truncateSync(value.filename, 16 * 1024 * 1024 + 100); }
    return result;
  });
  t.mock.method(Buffer, "allocUnsafe", size => { allocations.push(size); return allocate(size); });
  t.mock.method(fs, "readSync", (descriptor, buffer, offset, length, position) => {
    requested.push(length); return read(descriptor, buffer, offset, length, position);
  });
  assert.throws(() => readJson(value.filename, value.hashes, "input"), /json_input_changed_while_reading/);
  assert.deepEqual(allocations, [3]);
  assert.ok(requested.reduce((sum, length) => sum + length, 0) <= 3);
  assert.deepEqual(value.hashes, {});
});

for (const [label, mutate] of [
  ["growth", file => fs.appendFileSync(file, "x")],
  ["truncation", file => fs.truncateSync(file, 1)],
  ["same-size rewrite", file => { fs.writeFileSync(file, "[]"); fs.utimesSync(file, new Date(0), new Date(1_000)); }],
]) {
  test(`JSON rejects ${label} during descriptor reads`, t => {
    const value = jsonInputFixture(t), read = fs.readSync, close = fs.closeSync, stat = fs.fstatSync;
    let changed = false, closed;
    t.mock.method(fs, "readSync", (descriptor, ...args) => {
      if (!changed) { changed = true; mutate(value.filename); }
      return read(descriptor, ...args);
    });
    t.mock.method(fs, "closeSync", descriptor => { closed = descriptor; return close(descriptor); });
    assert.throws(() => readJson(value.filename, value.hashes, "input"), /json_input_changed_while_reading/);
    assert.deepEqual(value.hashes, {});
    assert.throws(() => stat(closed), { code: "EBADF" });
  });
}

test("JSON rejects symlink leaves with native nofollow or Windows descriptor-bound metadata", t => {
  const value = jsonInputFixture(t);
  const read = t.mock.method(fs, "readSync", () => { throw new Error("symlink_read_forbidden"); });
  if (fs.constants.O_NOFOLLOW) {
    const link = path.join(value.directory, "link.json"); fs.symlinkSync(value.filename, link);
    assert.throws(() => readJson(link, value.hashes, "input"), { code: "ELOOP" });
  } else {
    const lstat = fs.lstatSync;
    t.mock.method(fs, "lstatSync", (file, options) => Object.assign(Object.create(lstat(file, options)), { isSymbolicLink: () => true }));
    assert.throws(() => readJson(value.filename, value.hashes, "input"), /json_input_path_identity_changed/);
  }
  assert.equal(read.mock.callCount(), 0);
  assert.deepEqual(value.hashes, {});
});

test("JSON rejects a changed leaf identity before reading the opened descriptor", t => {
  const value = jsonInputFixture(t), lstat = fs.lstatSync;
  t.mock.method(fs, "lstatSync", (file, options) => {
    const result = lstat(file, options);
    return Object.assign(Object.create(result), { ino: result.ino + 1n });
  });
  const read = t.mock.method(fs, "readSync", () => { throw new Error("identity_read_forbidden"); });
  assert.throws(() => readJson(value.filename, value.hashes, "input"), /json_input_path_identity_changed/);
  assert.equal(read.mock.callCount(), 0);
  assert.deepEqual(value.hashes, {});
});

test("JSON never reopens a path replaced by an oversized file after descriptor validation", t => {
  const value = jsonInputFixture(t), read = fs.readSync, open = fs.openSync;
  const gateDescriptors = [], sizes = []; let changed = false;
  t.mock.method(fs, "openSync", (file, ...args) => {
    const descriptor = open(file, ...args);
    if (file === value.filename && !changed) gateDescriptors.push(descriptor);
    return descriptor;
  });
  t.mock.method(fs, "readSync", (descriptor, buffer, offset, length, position) => {
    if (!changed) {
      changed = true;
      fs.renameSync(value.filename, path.join(value.directory, "original.json"));
      fs.writeFileSync(value.filename, "[]"); fs.truncateSync(value.filename, 16 * 1024 * 1024 + 100);
    }
    sizes.push(buffer.length);
    assert.equal(descriptor, gateDescriptors[0]);
    return read(descriptor, buffer, offset, length, position);
  });
  try { assert.deepEqual(readJson(value.filename, value.hashes, "input"), {}); }
  catch (error) { assert.match(error.message, /^json_input_changed_while_reading$/); }
  assert.equal(gateDescriptors.length, 1);
  assert.ok(sizes.length > 0 && sizes.every(size => size === 3));
});

test("JSON closes the descriptor on invalid JSON without returning a parsed value", t => {
  const value = jsonInputFixture(t, "{"), close = fs.closeSync, stat = fs.fstatSync; let closed;
  t.mock.method(fs, "closeSync", descriptor => { closed = descriptor; return close(descriptor); });
  assert.throws(() => readJson(value.filename, value.hashes, "input"), SyntaxError);
  assert.throws(() => stat(closed), { code: "EBADF" });
});

for (const operation of ["fstatSync", "readSync"]) {
  test(`JSON closes the descriptor and preserves ${operation} failure`, t => {
    const value = jsonInputFixture(t), close = fs.closeSync, stat = fs.fstatSync; let closed;
    t.mock.method(fs, operation, () => { throw Object.assign(new Error("injected_io_error"), { code: "EIO" }); });
    t.mock.method(fs, "closeSync", descriptor => { closed = descriptor; return close(descriptor); });
    assert.throws(() => readJson(value.filename, value.hashes, "input"), { code: "EIO" });
    assert.deepEqual(value.hashes, {});
    assert.throws(() => stat(closed), { code: "EBADF" });
  });
}

test("JSON handles real short descriptor reads without path fallback", t => {
  const value = jsonInputFixture(t, '{"verified":true}'), read = fs.readSync;
  let calls = 0;
  t.mock.method(fs, "readSync", (descriptor, buffer, offset, length, position) => {
    calls += 1; return read(descriptor, buffer, offset, Math.min(length, 1), position);
  });
  assert.deepEqual(readJson(value.filename, value.hashes, "input"), { verified: true });
  assert.ok(calls > 2);
});

test("JSON rejects directories without reading content", t => {
  const value = jsonInputFixture(t);
  const read = t.mock.method(fs, "readSync", () => { throw new Error("directory_read_forbidden"); });
  assert.throws(() => readJson(value.directory, value.hashes, "input"), /json_input_not_regular_file|EISDIR/);
  assert.equal(read.mock.callCount(), 0);
});

test("JSON missing files fail on open without a precheck or fallback read", t => {
  const value = jsonInputFixture(t); fs.unlinkSync(value.filename);
  const stat = t.mock.method(fs, "statSync", () => { throw new Error("precheck_forbidden"); });
  assert.throws(() => readJson(value.filename, value.hashes, "input"), { code: "ENOENT" });
  assert.equal(stat.mock.callCount(), 0);
  assert.deepEqual(value.hashes, {});
});

test("JSON descriptor-close failure remains a failure, never a returned success", t => {
  const value = jsonInputFixture(t), close = fs.closeSync, stat = fs.fstatSync; let closed;
  t.mock.method(fs, "closeSync", descriptor => { closed = descriptor; close(descriptor); throw new Error("injected_close_failure"); });
  assert.throws(() => readJson(value.filename, value.hashes, "input"), /injected_close_failure/);
  assert.throws(() => stat(closed), { code: "EBADF" });
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

function absentOptionalMarkerFixture(reverse = false, peer = false) {
  const value = fixture();
  const first = value.lockTree.dependencies["@fixture/web"].dependencies.runtime;
  value.lock.packages["node_modules/runtime"].optional = true;
  value.workspaces["apps/web"].dependencies.second = "1.0.0";
  value.lock.packages["apps/web"].dependencies.second = "1.0.0";
  value.lock.packages["node_modules/second"] = { version: "1.0.0", license: "MIT-0", optional: true };
  const second = { name: "second", version: "1.0.0", license: "MIT-0", path: path.join(ROOT, "node_modules/second") };
  first.optional = true;
  value.lockTree.dependencies["@fixture/web"].dependencies.second = second;
  value.installedTree = structuredClone(value.lockTree);
  const installedWeb = value.installedTree.dependencies["@fixture/web"];
  delete installedWeb.dependencies.runtime.optional;
  const copies = [installedWeb.dependencies.runtime, installedWeb.dependencies.second];
  for (let index = 0; index < 4; index++) {
    const name = `dev-extra-${index}`;
    const license = index === 0 ? "AGPL-3.0-only" : "MIT";
    value.lock.packages[`node_modules/${name}`] = { version: "1.0.0", license, optional: true, dev: true };
    copies.push({ name, version: "1.0.0", license, path: path.join(ROOT, `node_modules/${name}`) });
  }
  const extras = copies.map(node => ({ ...node, extraneous: true,
    problems: [`extraneous: ${node.name}@${node.version} ${node.path}`] }));
  if (peer) {
    value.lock.packages["node_modules/runtime"].peerDependencies = { "dev-extra-0": "1.0.0" };
    value.lock.packages["node_modules/runtime"].peerDependenciesMeta = { "dev-extra-0": { optional: true } };
    installedWeb.dependencies.runtime.dependencies = { "dev-extra-0": { ...copies[2], extraneous: false } };
  }
  const entries = [...Object.entries(value.installedTree.dependencies), ...extras.map(node => [node.name, node])];
  value.installedTree.dependencies = Object.fromEntries(reverse ? entries.reverse() : entries);
  value.installedTree.problems = extras.flatMap(node => node.problems);
  return { value, extras };
}

function assertAbsentOptionalShape(result) {
  assert.equal(result.inventory_complete, true);
  assert.equal(result.exit_code, 1); // Graph reconciliation cannot waive the unreviewed MIT-0 runtime copy.
  assert.equal(result.counts.runtime_locations, 2);
  assert.equal(result.counts.unique_package_ids, 2);
  assert.equal(result.counts.installed, 2);
  assert.equal(result.installed_dev_only_extraneous.length, 4);
  assert.deepEqual(result.installed_dev_only_extraneous.map(node => node.id).sort(),
    Array.from({ length: 4 }, (_, index) => `dev-extra-${index}@1.0.0`));
  assert.ok(result.packages.every(node => node.installed_optional_extraneous));
  assert.deepEqual(result.policy_failures.map(node => [node.id, node.license]), [["second@1.0.0", "MIT-0"]]);
}

test("NATIVE-OPTIONAL absent npm marker retains two virtual copies and four visible dev-only extras", () => {
  const value = absentOptionalMarkerFixture();
  assert.ok(value.extras.every(node => !Object.hasOwn(node, "optional")));
  assertAbsentOptionalShape(report(value.value));
});

for (const reverse of [false, true]) {
  test(`NATIVE-OPTIONAL absent-marker repeated peer is traversal independent: ${reverse}`, () => {
    assertAbsentOptionalShape(report(absentOptionalMarkerFixture(reverse, true).value));
  });
}

for (const [label, marker] of [["false", false], ["null", null], ["string", "true"], ["number", 1], ["own undefined", undefined]]) {
  test(`NATIVE-OPTIONAL explicit ${label} native marker cannot borrow locked optionality`, () => {
    const value = absentOptionalMarkerFixture();
    value.extras[0].optional = marker;
    const result = report(value.value);
    assert.equal(result.exit_code, 2);
    assert.equal(result.inventory_complete, false);
    assert.ok(result.inventory_errors.includes("unreconciled_extraneous_package"));
  });
}

const absentMarkerCorruptions = {
  unknownName: value => { value.extras[0].name = "unknown-runtime"; },
  unlockedLocation: value => { value.extras[0].path = path.join(ROOT, "node_modules/unlocked-runtime"); },
  wrongVersion: value => { value.extras[0].version = "9.0.0"; },
  wrongLicense: value => { value.extras[0].license = "MIT-0"; },
  lockedOptionalFalse: value => { value.value.lock.packages["node_modules/runtime"].optional = false; },
  lockedOptionalAbsent: value => { delete value.value.lock.packages["node_modules/runtime"].optional; },
  lockedOptionalNonboolean: value => { value.value.lock.packages["node_modules/runtime"].optional = "true"; },
  linkedTarget: value => { Object.assign(value.value.lock.packages["node_modules/runtime"], { link: true, resolved: "node_modules/runtime" }); },
  unexpectedNondevCopy: value => { value.value.lock.packages["node_modules/dev-extra-0"].dev = false; },
  undeclaredChild: value => { value.extras[2].dependencies = { invented: { ...value.extras[0], extraneous: false, problems: [] } }; },
  unmatchedDiagnostic: value => { value.extras[2].problems.push("missing: invented@1.0.0"); },
};
for (const [name, mutate] of Object.entries(absentMarkerCorruptions)) {
  test(`NATIVE-OPTIONAL absent marker still rejects exact target/edge corruption: ${name}`, () => {
    const value = absentOptionalMarkerFixture();
    mutate(value);
    const result = report(value.value);
    assert.equal(result.exit_code, 2);
    assert.equal(result.inventory_complete, false);
    assert.equal(result.policy_passed, false);
    assert.ok(result.inventory_errors.length > 0);
  });
}
