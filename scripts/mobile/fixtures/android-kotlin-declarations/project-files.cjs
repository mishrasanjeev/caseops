const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { policy } = require('../../../../apps/mobile/plugins/kotlin-declaration-overlay.cjs');

// Public Gradle plugin-DSL regression. No Gradle internals or version tracker
// modification: exact catalog/literal supplier declarations feed real requests.
function projectFiles(buffers) {
  assert.ok(Array.isArray(buffers) && buffers.length === policy.targets.length);
  const inputs = buffers.map((bytes, index) => {
    assert.ok(Buffer.isBuffer(bytes));
    const hash = createHash('sha256').update(bytes).digest('hex'), target = policy.targets[index];
    assert.ok(hash === target.beforeSha256 || hash === target.afterSha256, 'NATIVE_KOTLIN_FIXTURE_UNKNOWN_SUPPLIER');
    return bytes.toString('utf8');
  });
  const literal = (index, id) => {
    const pattern = new RegExp('kotlin\\("' + id.replace('.', '\\.') + '"\\) version "[0-9.]+"', 'g');
    const matches = inputs[index].match(pattern);
    assert.equal(matches?.length, 1, 'NATIVE_KOTLIN_FIXTURE_LITERAL');
    return matches[0];
  };
  const files = new Map();
  files.set('settings.gradle.kts', 'pluginManagement { repositories { gradlePluginPortal(); mavenCentral() } }\n'
    + 'rootProject.name = "caseops-kotlin-declaration-regression"\n'
    + 'include(":rn-child", ":expo-autolinking", ":expo-core", ":expo-launcher", ":serialization-child")\n');
  files.set('gradle/libs.versions.toml', inputs[0]);
  files.set('build.gradle.kts', 'plugins {\n alias(libs.plugins.kotlin.jvm) apply false\n'
    + ' kotlin("plugin.serialization") version "2.4.20" apply false\n}\n'
    + 'tasks.register("verifyKotlinDeclarations") { doLast {\n'
    + ' val expected = setOf(":rn-child", ":expo-autolinking", ":expo-core", ":expo-launcher", ":serialization-child")\n'
    + ' check(subprojects.map { it.path }.toSet() == expected)\n'
    + ' subprojects.sortedBy { it.path }.forEach { child ->\n'
    + '  check(child.plugins.hasPlugin("org.jetbrains.kotlin.jvm"))\n'
    + '  val plugin = child.plugins.findPlugin("org.jetbrains.kotlin.jvm")!!\n'
    + '  println("CASEOPS_KOTLIN_REGRESSION_PROJECT " + child.path + " " + plugin.javaClass.name)\n'
    + ' }\n check(project(":serialization-child").plugins.hasPlugin("org.jetbrains.kotlin.plugin.serialization"))\n'
    + ' println("CASEOPS_KOTLIN_DECLARATION_REGRESSION_COMPLETE 5")\n} }\n');
  files.set('rn-child/build.gradle.kts', 'plugins { alias(libs.plugins.kotlin.jvm) }\n');
  files.set('expo-autolinking/build.gradle.kts', 'plugins { ' + literal(1, 'jvm') + ' }\n');
  files.set('expo-core/build.gradle.kts', 'plugins { ' + literal(4, 'jvm') + ' }\n');
  files.set('expo-launcher/build.gradle.kts', 'plugins { ' + literal(3, 'jvm') + ' }\n');
  files.set('serialization-child/build.gradle.kts', 'plugins { kotlin("jvm") version "2.4.20"; '
    + literal(2, 'plugin.serialization') + ' }\n');
  files.set('gradle.properties', 'org.gradle.daemon=false\norg.gradle.workers.max=2\norg.gradle.jvmargs=-Xmx512m\n');
  return files;
}
module.exports = { projectFiles };

