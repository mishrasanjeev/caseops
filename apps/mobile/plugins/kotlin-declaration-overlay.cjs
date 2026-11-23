const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash, randomBytes } = require('node:crypto');

// Exact declaration-only projection of the integrity-pinned npm suppliers.
// Package runtime code, dependency manifests and bundled notices are untouched.
const policy = {
  "kind": "caseops-pinned-kotlin-declaration-overlay-v1",
  "kotlinVersion": "2.4.20",
  "packages": {
    "@react-native/gradle-plugin": {
      "version": "0.88.0",
      "resolved": "https://registry.npmjs.org/@react-native/gradle-plugin/-/gradle-plugin-0.88.0.tgz",
      "integrity": "sha512-4jPSKslOfJj8NKY/jv9qmWkxZYmqPyamoS3Vs0JOFxw9t4PM6L/ea0fUsjNV0LxC9zJlvWilPJOCTOf7h8wlyw=="
    },
    "expo-modules-autolinking": {
      "version": "58.0.16",
      "resolved": "https://registry.npmjs.org/expo-modules-autolinking/-/expo-modules-autolinking-58.0.16.tgz",
      "integrity": "sha512-YglXoBBc3QwqqFfFQD1XVfpxXdF9RkuZOVxWTn5uHPiyvXSMFiVO16GnV+VSd+njKld1EJt7vQucCsDiLp4xVA=="
    },
    "expo-dev-launcher": {
      "version": "58.0.17",
      "resolved": "https://registry.npmjs.org/expo-dev-launcher/-/expo-dev-launcher-58.0.17.tgz",
      "integrity": "sha512-z2/F90do1q7Jgs6hnsY6Xjc1Sd7vKPMvw7Pp5Iv6M2qGHWprfydMCaUcwOkAQFoXqE2rLvd5hC1aSDFbH4oqRQ=="
    },
    "expo-modules-core": {
      "version": "58.0.28",
      "resolved": "https://registry.npmjs.org/expo-modules-core/-/expo-modules-core-58.0.28.tgz",
      "integrity": "sha512-2FCnT8mIubdQAHVtX9fVMN9qajF7hGDC3CjxxBG0HlyK7NEsxUDKkukiNVzqQpwiI+jJx7ysG0YvATwKKlu1sw=="
    }
  },
  "targets": [
    {
      "package": "@react-native/gradle-plugin",
      "relative": "gradle/libs.versions.toml",
      "beforeSha256": "c7a028cdee90f490de9493ca9de92b61b994844836161871091c340c568f109e",
      "afterSha256": "0f9f689c3362badd36d301ffe21a5f32b34c058dd425b529ad176bfcf14fd8c6",
      "beforeSize": 854,
      "afterSize": 855,
      "from": "kotlin = \"2.2.0\"",
      "to": "kotlin = \"2.4.20\"",
      "fixture": "1-original.txt"
    },
    {
      "package": "expo-modules-autolinking",
      "relative": "android/expo-gradle-plugin/build.gradle.kts",
      "beforeSha256": "f43a78068aaa078c40a55f6d165be415971e80cd98e0993046933953561a209f",
      "afterSha256": "17b81588947564e6f500f6a22ebc53132f57a39d734fdb61be44044a9ec40c39",
      "beforeSize": 84,
      "afterSize": 84,
      "from": "kotlin(\"jvm\") version \"2.2.21\"",
      "to": "kotlin(\"jvm\") version \"2.4.20\"",
      "fixture": "2-original.txt"
    },
    {
      "package": "expo-modules-autolinking",
      "relative": "android/expo-gradle-plugin/expo-autolinking-plugin-shared/build.gradle.kts",
      "beforeSha256": "e6876c3e2795e5bf9e6d9910d09ce75135e1ec14c33b0ddf41d4a549cac9d704",
      "afterSha256": "b4a33f4505e01d067407ee9f70a04078c1cbf876de6bfc935296468476db73d6",
      "beforeSize": 884,
      "afterSize": 884,
      "from": "kotlin(\"plugin.serialization\") version \"1.9.24\"",
      "to": "kotlin(\"plugin.serialization\") version \"2.4.20\"",
      "fixture": "3-original.txt"
    },
    {
      "package": "expo-dev-launcher",
      "relative": "expo-dev-launcher-gradle-plugin/build.gradle.kts",
      "beforeSha256": "fa57e74a7179891b599886d21141772b9676bee985bbe46f5b1c7304ae7633ef",
      "afterSha256": "3ffa942b673568acffb2a759d73c4f638511f5383be0a49265228fc6c0a86853",
      "beforeSize": 812,
      "afterSize": 812,
      "from": "kotlin(\"jvm\") version \"2.2.21\"",
      "to": "kotlin(\"jvm\") version \"2.4.20\"",
      "fixture": "4-original.txt"
    },
    {
      "package": "expo-modules-core",
      "relative": "expo-module-gradle-plugin/build.gradle.kts",
      "beforeSha256": "e882b17f84fc6b343b571dea8b5c7147584d795e0ebbb6b242c453984a2101aa",
      "afterSha256": "625df7436d0714aa4bb075bfb03bb362c1b73292ec4d499fc52fdb6cd4bd5b44",
      "beforeSize": 2083,
      "afterSize": 2083,
      "from": "kotlin(\"jvm\") version \"2.2.21\"",
      "to": "kotlin(\"jvm\") version \"2.4.20\"",
      "fixture": "5-original.txt"
    }
  ],
  "onlyVersionDeclarationsChanged": true,
  "noRuntimeCodeOrNoticeChanges": true
};
for (const row of Object.values(policy.packages)) Object.freeze(row);
for (const row of policy.targets) Object.freeze(row);
Object.freeze(policy.packages); Object.freeze(policy.targets); Object.freeze(policy);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const fields = ['dev', 'ino', 'mode', 'uid', 'gid', 'nlink', 'size', 'mtimeNs', 'ctimeNs'];
const identity = ['dev', 'ino', 'mode', 'uid', 'gid'];
const frame = (value, keys = fields) => keys.map(key => String(value[key]));
function bindNamed(opened, named, code) {
  assert.ok(named.isFile() && !named.isSymbolicLink(), code);
  for (const key of fields) {
    // Windows may expose dev=0 only on lstat. Descriptor comparisons always
    // retain every field, and nonzero named devices must still match.
    if (key === 'dev' && process.platform === 'win32' && named.dev === 0n) continue;
    assert.equal(named[key], opened[key], code);
  }
}

// The installation/prebuild owner must exclude all other consumers of these
// node_modules. All five inputs are admitted before the first replacement.
function applyKotlinDeclarations(projectRoot) {
  const started = performance.now(), end = started + 5000;
  let observations = 0, bytesRead = 0, primary;
  const opened = [], staged = [], admitted = [];
  const check = () => assert.ok(performance.now() < end, 'KOTLIN_OVERLAY_DEADLINE');
  const charge = (bytes = 0) => {
    check(); observations++; bytesRead += bytes;
    assert.ok(observations <= 5000 && bytesRead <= 1048576, 'KOTLIN_OVERLAY_INPUT_BOUND');
  };
  const named = file => { charge(); return fs.lstatSync(file, { bigint: true }); };
  assert.ok(typeof projectRoot === 'string' && path.isAbsolute(projectRoot), 'KOTLIN_OVERLAY_ROOT');
  const root = path.resolve(projectRoot);
  assert.equal(fs.realpathSync(root), root, 'KOTLIN_OVERLAY_CANONICAL_ROOT');
  const namespace = file => {
    const result = [];
    for (let parent = path.dirname(file); ; parent = path.dirname(parent)) {
      assert.ok(result.length < 128, 'KOTLIN_OVERLAY_NAMESPACE_BOUND');
      const value = named(parent);
      assert.ok(value.isDirectory() && !value.isSymbolicLink(), 'KOTLIN_OVERLAY_DIRECTORY');
      if (parent === root || parent.startsWith(root + path.sep))
        assert.equal(value.uid, BigInt(process.getuid?.() ?? 0), 'KOTLIN_OVERLAY_DIRECTORY_OWNER');
      result.push([parent, ...frame(value, identity)]);
      if (parent === path.dirname(parent)) break;
    }
    return result;
  };
  const admit = (file, writable = false) => {
    assert.ok(file.startsWith(root + path.sep), 'KOTLIN_OVERLAY_DIRECT_INPUT');
    const parents = namespace(file);
    const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    opened.push(fd);
    charge(); const before = fs.fstatSync(fd, { bigint: true });
    assert.ok(before.isFile() && before.nlink === 1n && before.uid === BigInt(process.getuid?.() ?? 0)
      && before.size > 0n && before.size <= (writable ? 65536n : 1048576n), 'KOTLIN_OVERLAY_OWNED_REGULAR');
    bindNamed(before, named(file), 'KOTLIN_OVERLAY_NAMED_INPUT');
    const data = fs.readFileSync(fd); charge(data.length);
    assert.equal(BigInt(data.length), before.size, 'KOTLIN_OVERLAY_INPUT_LENGTH');
    const item = { file, fd, before, data, parents };
    reconcile(item); admitted.push(item); return item;
  };
  const reconcile = item => {
    check(); charge();
    assert.deepEqual(frame(fs.fstatSync(item.fd, { bigint: true })), frame(item.before), 'KOTLIN_OVERLAY_DESCRIPTOR_CHANGED');
    bindNamed(item.before, named(item.file), 'KOTLIN_OVERLAY_PATH_CHANGED');
    assert.deepEqual(namespace(item.file), item.parents, 'KOTLIN_OVERLAY_PARENT_CHANGED');
  };
  try {
    const lock = admit(path.join(root, 'package-lock.json')), parsed = JSON.parse(lock.data.toString('utf8'));
    for (const [name, expected] of Object.entries(policy.packages)) {
      const row = parsed.packages?.['node_modules/' + name];
      for (const key of ['version', 'resolved', 'integrity'])
        assert.equal(row?.[key], expected[key], 'KOTLIN_OVERLAY_PINNED_LOCK');
      const manifest = admit(path.join(root, 'node_modules', name, 'package.json'));
      const actual = JSON.parse(manifest.data.toString('utf8'));
      assert.ok(actual.name === name && actual.version === expected.version, 'KOTLIN_OVERLAY_PINNED_PACKAGE');
    }
    const inputs = policy.targets.map(target => {
      const item = admit(path.join(root, 'node_modules', target.package, target.relative), true);
      const sha = digest(item.data);
      assert.ok(sha === target.beforeSha256 || sha === target.afterSha256, 'KOTLIN_OVERLAY_UNKNOWN_PREIMAGE');
      const changed = sha === target.beforeSha256;
      const text = item.data.toString('utf8');
      assert.ok(Buffer.from(text).equals(item.data), 'KOTLIN_OVERLAY_UTF8');
      let output = item.data;
      if (changed) {
        assert.equal(text.split(target.from).length - 1, 1, 'KOTLIN_OVERLAY_EXACT_DECLARATION');
        output = Buffer.from(text.replace(target.from, target.to));
      }
      assert.equal(output.length, target.afterSize, 'KOTLIN_OVERLAY_PROJECTED_SIZE');
      assert.equal(digest(output), target.afterSha256, 'KOTLIN_OVERLAY_PROJECTED_HASH');
      return Object.assign(item, { target, output, changed });
    });
    // Admission is complete, including the final path/descriptor observations.
    for (const input of admitted) reconcile(input);
    for (const input of inputs.filter(row => row.changed)) {
      check();
      const temp = path.join(path.dirname(input.file), '.caseops-kotlin-' + randomBytes(12).toString('hex') + '.tmp');
      const fd = fs.openSync(temp, fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_EXCL
        | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
      const entry = { temp, fd, input }; staged.push(entry);
      let written = 0;
      while (written < input.output.length) {
        check(); const amount = fs.writeSync(fd, input.output, written, input.output.length - written, written);
        assert.ok(amount > 0, 'KOTLIN_OVERLAY_WRITE_PROGRESS'); written += amount;
      }
      fs.fsyncSync(fd);
      const verify = Buffer.alloc(input.output.length + 1);
      assert.equal(fs.readSync(fd, verify, 0, verify.length, 0), input.output.length);
      assert.ok(verify.subarray(0, input.output.length).equals(input.output), 'KOTLIN_OVERLAY_STAGED_BYTES');
      const value = fs.fstatSync(fd, { bigint: true });
      assert.ok(value.isFile() && value.nlink === 1n && value.uid === BigInt(process.getuid?.() ?? 0),
        'KOTLIN_OVERLAY_PRIVATE_STAGE');
      bindNamed(value, named(temp), 'KOTLIN_OVERLAY_STAGED_PATH');
      entry.before = value;
    }
    // No vendor file is changed until every held input and staged buffer is ready.
    for (const input of admitted) reconcile(input);
    for (const entry of staged) {
      reconcile(entry.input);
      assert.deepEqual(frame(fs.fstatSync(entry.fd, { bigint: true })), frame(entry.before));
      bindNamed(entry.before, named(entry.temp), 'KOTLIN_OVERLAY_STAGED_PATH');
      fs.renameSync(entry.temp, entry.input.file);
      entry.renamed = true;
      entry.input.finalFd = entry.fd;
    }
    for (const input of inputs) {
      const fd = input.finalFd ?? input.fd;
      charge(); const value = fs.fstatSync(fd, { bigint: true });
      bindNamed(value, named(input.file), 'KOTLIN_OVERLAY_FINAL_PATH');
      const actual = Buffer.alloc(input.output.length + 1);
      assert.equal(fs.readSync(fd, actual, 0, actual.length, 0), input.output.length);
      charge(input.output.length);
      assert.ok(actual.subarray(0, input.output.length).equals(input.output), 'KOTLIN_OVERLAY_FINAL_BYTES');
      assert.deepEqual(frame(fs.fstatSync(fd, { bigint: true })), frame(value), 'KOTLIN_OVERLAY_FINAL_DESCRIPTOR');
      bindNamed(value, named(input.file), 'KOTLIN_OVERLAY_FINAL_RECONCILIATION');
      assert.deepEqual(namespace(input.file), input.parents, 'KOTLIN_OVERLAY_FINAL_NAMESPACE');
    }
    for (const input of admitted.filter(row => !row.changed)) reconcile(input);
    return { kind: policy.kind, kotlinVersion: policy.kotlinVersion, changed: staged.length,
      observations, bytesRead, records: inputs.map(row => ({ package: row.target.package,
        relative: row.target.relative, beforeSha256: digest(row.data),
        afterSha256: row.target.afterSha256, changed: row.changed })) };
  } catch (error) { primary = error; throw error; }
  finally {
    const errors = [];
    for (const entry of staged) {
      try { fs.closeSync(entry.fd); } catch (error) { errors.push(error); }
      if (!entry.renamed) try { fs.unlinkSync(entry.temp); } catch (error) { errors.push(error); }
    }
    for (const fd of opened) try { fs.closeSync(fd); } catch (error) { errors.push(error); }
    if (errors.length) {
      if (primary) primary.cleanupErrors = errors;
      else throw new AggregateError(errors, 'KOTLIN_OVERLAY_CLEANUP_FAILED');
    }
  }
}

module.exports = { applyKotlinDeclarations, policy };

