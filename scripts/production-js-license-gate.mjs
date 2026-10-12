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
      requireThat(installed && pinned.optional === true && !entry.link && (node.optional === true || !own(node, "optional"))
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

export function buildLicenseReport({ root, reviewRoot = root, manifest, workspaces, lock, lockTree, installedTree,
  lockExit = 0, installedExit = 0, reviewHashes = {} }) {
  const report = { schema_version: 1, completed: true, inventory_complete: false, policy_passed: false,
    allowed_licenses: [...ALLOWED_LICENSES], policy_sha256: hash(JSON.stringify(ALLOWED_LICENSES)),
    policy_semantics: "Exact allowlisted terms; AND requires both operands, OR elects the first approved alternative after the entire expression validates. Unused unapproved alternatives remain reported, not selected. WITH needs explicit approval. No license-text legal approval.",
    workspaces: [], packages: [], installed_dev_only_extraneous: [], inventory_errors: [], policy_failures: [], counts: {} };
  let reviewed = new Map(), reviewError;
  try { reviewed = readReviewedPackages(reviewRoot, reviewHashes); }
  catch (error) { reviewError = `review_registry_invalid:${error.code || error.message}`; }
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
      const review = reviewed.get(`${name}@${entry.version}`);
      const admission = !decision.approved && review && review.name === name && review.version === entry.version && review.license === entry.license
        && typeof entry.integrity === "string" && review.integrity === entry.integrity ? review : null;
      if (admission) { decision.approved = true; decision.reason = "exact_reviewed_managed_saas_package"; }
      const row = { location, id: `${name}@${entry.version}`, name, version: entry.version,
        license: entry.license ?? null, optional: entry.optional === true || entry.devOptional === true,
        install_status: actual ? "installed" : "lock_only_optional", installed_optional_extraneous: actual?.extraneous === true,
        lock_dev_flag: entry.dev === true, decision,
        ...(admission ? { review_admission: { scope: "managed-saas-only", integrity: admission.integrity,
          review_document: admission.review_document, materials: admission.materials } } : {}) };
      report.packages.push(row);
      if (!decision.approved) report.policy_failures.push({ location, id: row.id, license: row.license, ...decision });
    }
    requireThat([...installed.keys()].every(location => roots.has(location) || virtual.has(location)), "installed_runtime_package_not_in_virtual_graph");
    report.inventory_complete = true;
    report.policy_passed = report.policy_failures.length === 0;
  } catch (error) {
    report.inventory_errors.push(error.message);
  }
  if (reviewError) {
    report.inventory_errors.push(reviewError);
    report.inventory_complete = false;
    report.policy_passed = false;
  }
  report.counts = { workspaces: report.workspaces.length, runtime_locations: report.packages.length,
    unique_package_ids: new Set(report.packages.map(row => row.id)).size,
    installed: report.packages.filter(row => row.install_status === "installed").length,
    lock_only_optional: report.packages.filter(row => row.install_status === "lock_only_optional").length,
    policy_failures: report.policy_failures.length, inventory_errors: report.inventory_errors.length };
  report.exit_code = !report.inventory_complete ? 2 : report.policy_passed ? 0 : 1;
  return report;
}

function directoryIdentity(filename, reason = "input_parent_reparse_or_not_directory") {
  const directory = path.dirname(path.resolve(filename)), parsed = path.parse(directory);
  const paths = [parsed.root];
  for (const segment of directory.slice(parsed.root.length).split(path.sep).filter(Boolean)) paths.push(path.join(paths.at(-1), segment));
  return paths.map(file => {
    const metadata = fs.lstatSync(file, { bigint: true });
    requireThat(metadata.isDirectory() && !metadata.isSymbolicLink(), reason);
    const resolved = fs.realpathSync.native(file);
    requireThat(process.platform === "win32" ? resolved.toLowerCase() === file.toLowerCase() : resolved === file,
      reason);
    return { file, dev: metadata.dev, ino: metadata.ino };
  });
}

function sameDirectories(before, after) {
  return before.length === after.length && before.every((value, index) => value.file === after[index].file
    && value.dev === after[index].dev && value.ino === after[index].ino);
}

function readBoundedBytes(filename, maximum, validatePath) {
  // libuv's Windows lstat exposes device zero while fstat exposes the volume ID.
  // Bind the inode and unchanged non-reparse ancestor chain in that native case.
  const parents = process.platform === "win32" ? directoryIdentity(filename, "json_input_path_identity_changed") : null;
  const descriptor = fs.openSync(filename, fs.constants.O_RDONLY
    | (fs.constants.O_NOFOLLOW || 0) | (fs.constants.O_NONBLOCK || 0));
  try {
    const before = fs.fstatSync(descriptor, { bigint: true });
    requireThat(before.isFile(), "json_input_not_regular_file");
    requireThat(before.size >= 0n && before.size <= BigInt(maximum), "oversized_json_input");
    // Windows lacks O_NOFOLLOW. On every platform, bind the non-symlink leaf
    // to the already-open descriptor before reading; never reopen the path.
    const entry = fs.lstatSync(filename, { bigint: true });
    requireThat(entry.isFile() && !entry.isSymbolicLink() && before.ino > 0n
      && (entry.dev === before.dev || (process.platform === "win32" && entry.dev === 0n && before.dev > 0n))
      && entry.ino === before.ino, "json_input_path_identity_changed");
    if (parents) requireThat(sameDirectories(parents, directoryIdentity(filename, "json_input_path_identity_changed")), "json_input_path_identity_changed");
    if (validatePath) validatePath(before);
    const size = Number(before.size);
    const buffer = Buffer.allocUnsafe(size + 1);
    let length = 0;
    while (length < buffer.length) {
      const count = fs.readSync(descriptor, buffer, length, Math.min(64 * 1024, buffer.length - length), length);
      if (count === 0) break;
      length += count;
    }
    const after = fs.fstatSync(descriptor, { bigint: true });
    requireThat(length === size && after.size === before.size && after.mtimeNs === before.mtimeNs
      && after.ctimeNs === before.ctimeNs, "json_input_changed_while_reading");
    if (parents) requireThat(sameDirectories(parents, directoryIdentity(filename, "json_input_changed_while_reading")), "json_input_changed_while_reading");
    if (validatePath) validatePath(after);
    return buffer.subarray(0, length);
  } finally {
    fs.closeSync(descriptor);
  }
}

export function readJson(filename, hashes, label) {
  const raw = readBoundedBytes(filename, 16 * 1024 * 1024);
  hashes[label] = hash(raw);
  return JSON.parse(raw.toString("utf8"));
}

function reviewPath(relative) {
  requireThat(typeof relative === "string" && relative.length <= 512 && !/[\\:\x00-\x1f\x7f]/.test(relative)
    && relative.split("/").every(segment => segment && !segment.startsWith(".") && !/[ .]$/.test(segment))
    && !path.posix.isAbsolute(relative) && !path.win32.isAbsolute(relative)
    && (relative.startsWith("license-policy/") || relative.startsWith("apps/web/public/third-party-notices/")
      || relative === "docs/security/js-license-compliance-review-2026-10-12.md"), "review_path_forbidden");
  return relative;
}

function readReviewBytes(root, relative, maximum, allowMissing = false) {
  const filename = path.join(root, reviewPath(relative));
  let parents, leaf;
  try { parents = directoryIdentity(filename); leaf = fs.lstatSync(filename, { bigint: true }); }
  catch (error) { if (allowMissing && error.code === "ENOENT") return null; throw error; }
  requireThat(leaf.isFile() && !leaf.isSymbolicLink(), "review_material_not_regular_file");
  return readBoundedBytes(filename, maximum, metadata => {
    requireThat(sameDirectories(parents, directoryIdentity(filename)), "review_path_changed");
    const current = fs.lstatSync(filename, { bigint: true });
    requireThat(current.isFile() && !current.isSymbolicLink() && current.dev === leaf.dev
      && current.ino === leaf.ino && current.ino === metadata.ino && current.size === metadata.size,
      "review_path_changed");
  });
}

function exactKeys(value, keys) {
  requireThat(plain(value) && Object.keys(value).sort().join("\n") === [...keys].sort().join("\n"), "review_schema_fields");
}

function parseReviewJson(raw) {
  const text = raw.toString("utf8"), parsed = JSON.parse(text);
  // JSON.parse keeps the last duplicate key. Reject ambiguity in this policy input.
  const tokens = text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]|[^\s{}\[\]:,]+/g) || [];
  let cursor = 0;
  function visit(depth) {
    requireThat(depth <= 32, "review_json_depth");
    const token = tokens[cursor++];
    if (token === "{") {
      const keys = new Set();
      while (tokens[cursor] !== "}") {
        const key = JSON.parse(tokens[cursor++]);
        requireThat(!keys.has(key), "review_duplicate_json_key"); keys.add(key);
        requireThat(tokens[cursor++] === ":", "review_json_syntax"); visit(depth + 1);
        if (tokens[cursor] !== ",") break;
        cursor++;
      }
      requireThat(tokens[cursor++] === "}", "review_json_syntax");
    } else if (token === "[") {
      while (tokens[cursor] !== "]") {
        visit(depth + 1);
        if (tokens[cursor] !== ",") break;
        cursor++;
      }
      requireThat(tokens[cursor++] === "]", "review_json_syntax");
    }
  }
  visit(0);
  requireThat(cursor === tokens.length, "review_json_syntax");
  return parsed;
}

function readReviewedPackages(root, hashes) {
  requireThat(typeof root === "string" && root.length > 0 && !root.split(/[\\/]/).includes(".."), "review_root_invalid");
  let supplied;
  try { supplied = fs.lstatSync(root, { bigint: true }); }
  catch (error) { if (error.code === "ENOENT") return new Map(); throw error; }
  requireThat(supplied.isDirectory() && !supplied.isSymbolicLink(), "review_root_reparse_or_not_directory");
  root = path.resolve(root);
  const registryPath = "license-policy/reviewed-packages.json";
  const raw = readReviewBytes(root, registryPath, 128 * 1024, true);
  if (raw === null) return new Map();
  hashes[registryPath] = hash(raw);
  const registry = parseReviewJson(raw);
  exactKeys(registry, ["schema_version", "scope", "review_document", "packages"]);
  requireThat(registry.schema_version === 1 && registry.scope === "managed-saas-only", "review_schema_or_scope");
  requireThat(Array.isArray(registry.packages) && registry.packages.length >= 1 && registry.packages.length <= 32, "review_entry_bound");
  const references = new Map(), ids = new Set();
  function reference(value) {
    exactKeys(value, ["path", "sha256"]);
    reviewPath(value.path);
    requireThat(typeof value.sha256 === "string" && /^[a-f0-9]{64}$/.test(value.sha256), "review_hash_shape");
    requireThat(!references.has(value.path) || references.get(value.path) === value.sha256, "review_conflicting_material_hash");
    references.set(value.path, value.sha256);
  }
  exactKeys(registry.review_document, ["path", "sha256"]);
  requireThat(registry.review_document.path === "docs/security/js-license-compliance-review-2026-10-12.md", "review_document_path");
  reference(registry.review_document);
  for (const entry of registry.packages) {
    exactKeys(entry, ["name", "version", "license", "integrity", "materials"]);
    for (const [field, maximum] of [["name", 214], ["version", 128], ["license", 2048], ["integrity", 512]]) {
      requireThat(typeof entry[field] === "string" && entry[field].length > 0
        && [...entry[field]].length <= maximum && !/[\x00-\x1f\x7f-\x9f]/u.test(entry[field]), "review_identity_shape");
    }
    // Buffer's base64 decoder alone silently accepts whitespace and invalid bytes.
    requireThat(/^sha512-[A-Za-z0-9+/]{86}==$/.test(entry.integrity), "review_integrity_shape");
    const digest = Buffer.from(entry.integrity.slice(7), "base64");
    requireThat(digest.length === 64 && digest.toString("base64") === entry.integrity.slice(7), "review_integrity_shape");
    const id = `${entry.name}@${entry.version}`;
    requireThat(!ids.has(id), "review_duplicate_package_id"); ids.add(id);
    requireThat(Array.isArray(entry.materials) && entry.materials.length > 0 && entry.materials.length <= 32, "review_material_bound");
    for (const material of entry.materials) reference(material);
    requireThat(new Set(entry.materials.map(value => value.path)).size === entry.materials.length, "review_duplicate_material");
  }
  requireThat(references.size <= 64, "review_global_material_bound");
  // Validate the entire schema and every path before reading any declared content.
  // Digests are per-invocation only; the next reconciliation reopens and revalidates.
  for (const [relative, expected] of references) {
    const digest = hash(readReviewBytes(root, relative, 1024 * 1024));
    requireThat(digest === expected, "review_material_hash_mismatch");
    hashes[relative] = digest;
  }
  return new Map(registry.packages.map(entry => [`${entry.name}@${entry.version}`,
    { ...entry, review_document: registry.review_document }]));
}

export function main(argv) {
  const options = {};
  requireThat(argv.length % 2 === 0, "invalid_arguments");
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    requireThat(["--root", "--review-root", "--lock-tree", "--installed-tree", "--lock-exit", "--installed-exit", "--source-sha", "--output"].includes(key)
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
    report = buildLicenseReport({ root, reviewRoot: options["--review-root"] || root, reviewHashes: hashes,
      manifest, workspaces, lock, lockTree, installedTree, lockExit, installedExit });
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
