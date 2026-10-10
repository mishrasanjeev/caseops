import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

// Unchanged terms from the former security.yml --onlyAllow argument.
export const ALLOWED_LICENSES = Object.freeze([
  "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "PostgreSQL",
  "Python-2.0", "Unlicense", "CC0-1.0", "0BSD", "BlueOak-1.0.0",
  "CC-BY-4.0", "CC-BY-3.0", "Apache 2.0",
]);
const allowed = new Set(ALLOWED_LICENSES);
const hash = value => createHash("sha256").update(value).digest("hex");
const plain = value => value !== null && typeof value === "object" && !Array.isArray(value);
const requireThat = (value, reason) => { if (!value) throw new Error(reason); };
const own = (value, key) => Object.hasOwn(value, key);

export function licenseDecision(expression) {
  if (typeof expression !== "string" || !expression.trim() || expression.length > 2048) {
    return { approved: false, reason: "missing_or_invalid_license", selected_terms: [], unapproved_terms: [], unused_unapproved_terms: [] };
  }
  if (expression === "Apache 2.0") return { approved: true, reason: "legacy_exact_allowlist_term", selected_terms: [expression], unapproved_terms: [], unused_unapproved_terms: [] };
  // Deliberately no guessed SPDX correction, substring matching or exception waiver.
  const tokens = expression.match(/[A-Za-z0-9][A-Za-z0-9.+:-]*|[()]|\S/g) || [];
  const unapproved = new Set();
  let cursor = 0;
  function term(depth) {
    requireThat(depth <= 32 && tokens.length <= 256, "license_expression_bound");
    if (tokens[cursor] === "(") {
      cursor += 1;
      const result = or(depth + 1);
      requireThat(tokens[cursor++] === ")", "invalid_license_expression");
      return result;
    }
    const identifier = tokens[cursor++];
    const identifierPattern = /^(DocumentRef-|LicenseRef-)/.test(identifier)
      ? /^(?:DocumentRef-[A-Za-z0-9.-]+:)?LicenseRef-[A-Za-z0-9.-]+$/ : /^[A-Za-z0-9][A-Za-z0-9.-]*\+?$/;
    requireThat(typeof identifier === "string" && identifierPattern.test(identifier)
      && !["AND", "OR", "WITH"].includes(identifier), "invalid_license_expression");
    let approved = allowed.has(identifier);
    if (!approved) unapproved.add(identifier);
    if (tokens[cursor] === "WITH") {
      cursor += 1;
      const exception = tokens[cursor++];
      requireThat(typeof exception === "string" && /^[A-Za-z0-9][A-Za-z0-9.-]*$/.test(exception)
        && !["AND", "OR", "WITH"].includes(exception), "invalid_license_expression");
      unapproved.add(`${identifier} WITH ${exception}`);
      approved = false;
    }
    return { approved, selected_terms: approved ? [identifier] : [] };
  }
  function and(depth) {
    let result = term(depth);
    while (tokens[cursor] === "AND") {
      cursor += 1;
      const next = term(depth);
      const approved = result.approved && next.approved;
      result = { approved, selected_terms: approved ? [...result.selected_terms, ...next.selected_terms] : [] };
    }
    return result;
  }
  function or(depth) {
    let result = and(depth);
    while (tokens[cursor] === "OR") {
      cursor += 1;
      // Parse the entire alternative even after an approved choice. A Boolean
      // short circuit must not hide malformed syntax or an exceeded bound.
      const next = and(depth);
      if (!result.approved) result = next;
    }
    return result;
  }
  try {
    const result = or(0);
    requireThat(cursor === tokens.length, "invalid_license_expression");
    const terms = [...unapproved].sort();
    return { approved: result.approved, reason: result.approved ? (terms.length ? "approved_spdx_alternative" : "approved_spdx_terms") : "license_policy_review_required",
      selected_terms: [...new Set(result.selected_terms)].sort(), unapproved_terms: terms,
      unused_unapproved_terms: result.approved ? terms : [] };
  } catch {
    return { approved: false, reason: "invalid_or_oversized_license_expression", selected_terms: [],
      unapproved_terms: [...unapproved].sort(), unused_unapproved_terms: [] };
  }
}

function normalizeLocation(root, value) {
  requireThat(typeof value === "string" && path.isAbsolute(value), "native_package_path_missing");
  const relative = path.relative(root, value).split(path.sep).join("/");
  requireThat(relative !== ".." && !relative.startsWith("../") && !path.isAbsolute(relative), "native_package_path_outside_root");
  return relative;
}

function graphPackages(tree, root, packages, installed = false) {
  const rows = new Map();
  const stack = [tree];
  const diagnostics = [];
  const optionalExtras = new Set();
  const optionalExtraLocations = new Set();
  let visits = 0;
  while (stack.length) {
    const node = stack.pop();
    requireThat(++visits <= 100_000 && plain(node), "invalid_or_oversized_native_graph");
    requireThat(!node.error && !node.missing && !node.invalid
      && (!node.problems || (Array.isArray(node.problems) && node.problems.every(value => typeof value === "string"))), "native_graph_dependency_problem");
    diagnostics.push(...node.problems || []);
    if (!node.path && Object.keys(node).length === 0) continue; // npm's absent optional peer placeholder.
    const location = normalizeLocation(root, node.path);
    requireThat(own(packages, location), "native_package_not_locked");
    const entry = packages[location];
    const target = entry.link ? entry.resolved : location;
    requireThat(typeof target === "string" && own(packages, target), "missing_or_external_link_target");
    if (node.extraneous) {
      const pinned = packages[target];
      requireThat(installed && pinned.optional === true && !entry.link && node.optional === true
        && node.version === pinned.version && node.name === (pinned.name || target.split("node_modules/").at(-1))
        && JSON.stringify(node.license) === JSON.stringify(pinned.license), "unreconciled_extraneous_package");
      optionalExtras.add(`extraneous: ${node.name}@${node.version} ${node.path}`);
      optionalExtraLocations.add(target);
    }
    const record = { ...node, location: target };
    const previous = rows.get(target);
    if (previous) requireThat(previous.name === node.name && previous.version === node.version
      && JSON.stringify(previous.license) === JSON.stringify(node.license), "native_duplicate_identity_conflict");
    else rows.set(target, record);
    requireThat(!node.dependencies || plain(node.dependencies), "invalid_native_dependencies");
    const pinned = packages[target];
    const declared = new Set(Object.keys({ ...pinned.dependencies, ...pinned.optionalDependencies, ...pinned.peerDependencies }));
    if (target === "") for (const workspace of packages[""].workspaces || []) declared.add(packages[workspace]?.name);
    requireThat(Object.entries(node.dependencies || {}).every(([name, child]) => declared.has(name)
      || (installed && child.extraneous === true)), "undeclared_native_runtime_edge");
    stack.push(...Object.values(node.dependencies || {}));
  }
  requireThat(diagnostics.every(value => optionalExtras.has(value)), "native_graph_dependency_problem");
  // npm can repeat an optional extra as a non-extraneous peer child. Its
  // validated diagnostic belongs to the physical location, not traversal order.
  for (const location of optionalExtraLocations) rows.get(location).extraneous = true;
  const devExtras = [...rows.values()].filter(node => optionalExtraLocations.has(node.location) && packages[node.location].dev === true);
  return { rows, devExtras };
}

export function buildLicenseReport({ root, manifest, workspaces, lock, lockTree, installedTree,
  lockExit = 0, installedExit = 0 }) {
  const report = { schema_version: 1, completed: true, inventory_complete: false, policy_passed: false,
    allowed_licenses: [...ALLOWED_LICENSES], policy_sha256: hash(JSON.stringify(ALLOWED_LICENSES)),
    policy_semantics: "Exact allowlisted terms; AND requires both operands, OR elects the first approved alternative after the entire expression validates. Unused unapproved alternatives remain reported, not selected. WITH needs explicit approval. No license-text legal approval.",
    workspaces: [], packages: [], installed_dev_only_extraneous: [], inventory_errors: [], policy_failures: [], counts: {} };
  try {
    requireThat(lockExit === 0 && installedExit === 0, "native_npm_inventory_failed");
    requireThat(plain(manifest) && plain(lock) && lock.lockfileVersion === 3 && plain(lock.packages), "unsupported_or_missing_lockfile");
    const packages = lock.packages;
    requireThat(Object.keys(packages).length <= 20_000 && plain(packages[""]), "invalid_or_oversized_lock_inventory");
    const workspacePaths = manifest.workspaces ?? [];
    requireThat(Array.isArray(workspacePaths) && workspacePaths.every(value => typeof value === "string"
      && value !== "" && !/[\\*?![\]{}]/.test(value) && path.posix.normalize(value) === value
      && !value.startsWith("../") && !path.isAbsolute(value)), "unsupported_workspace_pattern");
    requireThat(new Set(workspacePaths).size === workspacePaths.length, "duplicate_workspace");
    requireThat(JSON.stringify(packages[""].workspaces || []) === JSON.stringify(workspacePaths), "root_workspace_lock_drift");
    requireThat(plain(workspaces) && Object.keys(workspaces).sort().join("\n") === [...workspacePaths].sort().join("\n"), "missing_or_extra_workspace_manifest");
    const roots = new Map([["", manifest], ...workspacePaths.map(location => [location, workspaces[location]])]);
    for (const [location, source] of roots) {
      const pinned = packages[location];
      requireThat(plain(source) && plain(pinned) && source.name === pinned.name && source.version === pinned.version, "workspace_identity_lock_drift");
      for (const field of ["dependencies", "optionalDependencies", "devDependencies", "peerDependencies", "peerDependenciesMeta"]) {
        requireThat(JSON.stringify(Object.entries(source[field] || {}).sort()) === JSON.stringify(Object.entries(pinned[field] || {}).sort()), "workspace_dependency_lock_drift");
      }
      const decision = source.private === true ? null : licenseDecision(source.license);
      report.workspaces.push({ location, name: source.name, private: source.private === true,
        runtime_dependencies: Object.keys({ ...source.dependencies, ...source.optionalDependencies }).sort(), license_decision: decision });
      if (decision && !decision.approved) report.policy_failures.push({ location, id: `${source.name}@${source.version}`,
        license: source.license ?? null, first_party: true, ...decision });
    }
    const virtual = graphPackages(lockTree, root, packages).rows;
    const actualGraph = graphPackages(installedTree, root, packages, true);
    const installed = actualGraph.rows;
    const devExtras = actualGraph.devExtras.filter(node => !virtual.has(node.location));
    for (const node of devExtras) installed.delete(node.location);
    report.installed_dev_only_extraneous = devExtras.map(node => ({ location: node.location,
      id: `${node.name}@${node.version}`, license: node.license, reason: "Locked dev-only optional package, absent from production virtual graph." }));
    for (const [location, source] of roots) {
      requireThat(virtual.has(location) && installed.has(location), "workspace_omitted_from_native_graph");
      requireThat(virtual.get(location).name === source.name && installed.get(location).name === source.name
        && virtual.get(location).version === source.version && installed.get(location).version === source.version,
        "native_workspace_identity_mismatch");
      for (const name of Object.keys({ ...source.dependencies, ...source.optionalDependencies })) {
        requireThat(own(virtual.get(location).dependencies || {}, name), "direct_runtime_dependency_omitted");
      }
    }
    // npm's peer closure can legitimately reach a lock entry marked dev. Include
    // it rather than dropping a runtime edge solely because of that flag.
    const expected = [...virtual.keys()].filter(location => !roots.has(location)).map(location => [location, packages[location]]);
    requireThat(expected.length > 0, "empty_production_inventory");
    requireThat(Object.entries(packages).every(([location, entry]) => roots.has(location) || entry.link
      || entry.dev === true || virtual.has(location)), "locked_runtime_package_omitted");
    for (const [location, entry] of expected.sort(([a], [b]) => a.localeCompare(b))) {
      requireThat(plain(entry) && typeof entry.version === "string" && entry.version.length > 0 && virtual.has(location), "locked_runtime_package_omitted");
      const node = virtual.get(location);
      const name = entry.name || location.split("node_modules/").at(-1);
      requireThat(node.name === name && node.version === entry.version
        && JSON.stringify(node.license) === JSON.stringify(entry.license), "native_lock_metadata_mismatch");
      const actual = installed.get(location);
      requireThat(actual || entry.optional === true || entry.devOptional === true, "required_installed_package_missing");
      if (actual) requireThat(actual.name === name && actual.version === entry.version
        && JSON.stringify(actual.license) === JSON.stringify(entry.license), "installed_metadata_lock_mismatch");
      const decision = licenseDecision(entry.license);
      const row = { location, id: `${name}@${entry.version}`, name, version: entry.version,
        license: entry.license ?? null, optional: entry.optional === true || entry.devOptional === true,
        install_status: actual ? "installed" : "lock_only_optional", installed_optional_extraneous: actual?.extraneous === true,
        lock_dev_flag: entry.dev === true, decision };
      report.packages.push(row);
      if (!decision.approved) report.policy_failures.push({ location, id: row.id, license: row.license, ...decision });
    }
    requireThat([...installed.keys()].every(location => roots.has(location) || virtual.has(location)), "installed_runtime_package_not_in_virtual_graph");
    report.inventory_complete = true;
    report.policy_passed = report.policy_failures.length === 0;
  } catch (error) {
    report.inventory_errors.push(error.message);
  }
  report.counts = { workspaces: report.workspaces.length, runtime_locations: report.packages.length,
    unique_package_ids: new Set(report.packages.map(row => row.id)).size,
    installed: report.packages.filter(row => row.install_status === "installed").length,
    lock_only_optional: report.packages.filter(row => row.install_status === "lock_only_optional").length,
    policy_failures: report.policy_failures.length, inventory_errors: report.inventory_errors.length };
  report.exit_code = !report.inventory_complete ? 2 : report.policy_passed ? 0 : 1;
  return report;
}

function readJson(filename, hashes, label) {
  requireThat(fs.statSync(filename).size <= 16 * 1024 * 1024, "oversized_json_input");
  const raw = fs.readFileSync(filename);
  requireThat(raw.length <= 16 * 1024 * 1024, "oversized_json_input");
  hashes[label] = hash(raw);
  return JSON.parse(raw.toString("utf8"));
}

export function main(argv) {
  const options = {};
  requireThat(argv.length % 2 === 0, "invalid_arguments");
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    requireThat(["--root", "--lock-tree", "--installed-tree", "--lock-exit", "--installed-exit", "--source-sha", "--output"].includes(key)
      && !own(options, key), "invalid_arguments");
    options[key] = argv[index + 1];
  }
  requireThat(options["--output"] && /^[a-f0-9]{40}$/.test(options["--source-sha"] || ""), "missing_output_or_source_identity");
  const root = path.resolve(options["--root"] || ".");
  const hashes = {};
  let report;
  try {
    const manifest = readJson(path.join(root, "package.json"), hashes, "package.json");
    const lock = readJson(path.join(root, "package-lock.json"), hashes, "package-lock.json");
    const workspaces = {};
    requireThat(Array.isArray(manifest.workspaces || []) && (manifest.workspaces || []).every(value => typeof value === "string"
      && !/[\\*?![\]{}]/.test(value) && value !== "" && path.posix.normalize(value) === value
      && !value.startsWith("../") && !path.isAbsolute(value)), "unsupported_workspace_pattern");
    for (const location of manifest.workspaces || []) {
      workspaces[location] = readJson(path.join(root, location, "package.json"), hashes, `${location}/package.json`);
    }
    const lockTree = readJson(path.resolve(options["--lock-tree"]), hashes, "native_lock_tree");
    const installedTree = readJson(path.resolve(options["--installed-tree"]), hashes, "native_installed_tree");
    const lockExit = Number(options["--lock-exit"] ?? 0);
    const installedExit = Number(options["--installed-exit"] ?? 0);
    requireThat([lockExit, installedExit].every(value => Number.isInteger(value) && value >= 0 && value <= 255), "invalid_native_exit_status");
    report = buildLicenseReport({ root, manifest, workspaces, lock, lockTree, installedTree, lockExit, installedExit });
  } catch (error) {
    report = { schema_version: 1, completed: true, inventory_complete: false, policy_passed: false,
      inventory_errors: [error.code || error.name], packages: [], exit_code: 2 };
  }
  report.source_sha = options["--source-sha"];
  report.started_and_finished_scope = "One offline native inventory reconciliation; no registry/provider calls or license authorization.";
  report.finished_at = new Date().toISOString();
  report.input_sha256 = hashes;
  report.script_sha256 = hash(fs.readFileSync(new URL(import.meta.url)));
  const file = fs.openSync(path.resolve(options["--output"]), "wx");
  try { fs.writeFileSync(file, JSON.stringify(report, null, 2) + "\n"); fs.fsyncSync(file); }
  finally { fs.closeSync(file); }
  console.log(JSON.stringify({ completed: true, inventory_complete: report.inventory_complete,
    policy_passed: report.policy_passed, counts: report.counts, inventory_errors: report.inventory_errors, exit_code: report.exit_code }));
  return report.exit_code;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { process.exitCode = main(process.argv.slice(2)); }
  catch (error) { console.error(JSON.stringify({ completed: false, error: error.code || error.name })); process.exitCode = 2; }
}
