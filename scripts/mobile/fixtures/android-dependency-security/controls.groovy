import groovy.json.JsonSlurper
import groovy.json.JsonOutput
import java.nio.charset.StandardCharsets
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest

final class DependencyContract {
    final Map requested
    Map target
    final List<String> selected = []
    DependencyContract(String key, String version, String targetVersion) {
        def parts = key.split(':', -1)
        assert parts.size() == 2
        requested = [group: parts[0], name: parts[1], version: version]
        target = [group: parts[0], name: parts[1], version: targetVersion]
    }
    void useVersion(String version) {
        assert version && selected.empty
        selected.add(version)
        target = [group: target.group, name: target.name, version: version]
    }
}
final class ResolutionContract {
    final List<Closure> rules = []
    void eachDependency(Closure rule) { rules.add(rule) }
    DependencyContract resolve(String key, String requested, String target) {
        def result = new DependencyContract(key, requested, target)
        rules.each { it.call(result) }
        result
    }
}
final class ConfigurationContract {
    final String name
    final ResolutionContract resolutionStrategy = new ResolutionContract()
    ConfigurationContract(String value) { name = value }
}
final class ConfigurationsContract {
    final List<ConfigurationContract> rows = []
    final List<Closure> listeners = []
    void configureEach(Closure listener) {
        listeners.add(listener)
        rows.each { listener.call(it) }
    }
    ConfigurationContract add(String name) {
        def result = new ConfigurationContract(name)
        rows.add(result)
        listeners.each { it.call(result) }
        result
    }
}
final class HandlerContract {
    final ConfigurationsContract configurations = new ConfigurationsContract()
}
final class PluginContract {
    final Map requested
    final List<String> selected = []
    PluginContract(String id, String version) { requested = [id: [id: id], version: version] }
    void useVersion(String version) { assert version && selected.empty; selected.add(version) }
}
final class PluginResolutionContract {
    final List<Closure> rules = []
    void eachPlugin(Closure rule) { rules.add(rule) }
    PluginContract resolve(String id, String version) {
        def result = new PluginContract(id, version)
        rules.each { it.call(result) }
        result
    }
}
final class SettingsContract {
    final HandlerContract buildscript = new HandlerContract()
    final Map pluginManagement = [resolutionStrategy: new PluginResolutionContract()]
}
final class ProjectContract {
    final String path
    final HandlerContract buildscript = new HandlerContract()
    final ConfigurationsContract configurations = new ConfigurationsContract()
    ProjectContract(String value) { path = value }
}
final class GradleContract {
    final List<Closure> settingsHooks = []
    final List<Closure> projectHooks = []
    void beforeSettings(Closure hook) { settingsHooks.add(hook) }
    void beforeProject(Closure hook) { projectHooks.add(hook) }
    void settings(SettingsContract value) { settingsHooks.each { it.call(value) } }
    void project(ProjectContract value) { projectHooks.each { it.call(value) } }
}

final List<String> CASE_IDS = ["ANDROID-SECURITY-CONTROL-01", "ANDROID-SECURITY-CONTROL-02", "ANDROID-SECURITY-CONTROL-03", "ANDROID-SECURITY-CONTROL-04", "ANDROID-SECURITY-CONTROL-05", "ANDROID-SECURITY-CONTROL-06", "ANDROID-SECURITY-CONTROL-07", "ANDROID-SECURITY-CONTROL-08", "ANDROID-SECURITY-CONTROL-09", "ANDROID-SECURITY-CONTROL-10"]
assert CASE_IDS.size() == 10 && CASE_IDS.toSet().size() == 10
final int MAX_WIRE = 65536, MAX_SOURCE = 32768, PREFIX_BYTES = 29316
final String PREFIX_SHA = 'c63f8bfd68e2dedd8e7ad037d02c8281dc14b4fdadc9a56921a975bdeeba2fc2'
def sha = { byte[] value -> MessageDigest.getInstance('SHA-256').digest(value).encodeHex().toString() }
def wire = new ByteArrayOutputStream()
byte[] buffer = new byte[4096]
for (;;) {
    int count = System.in.read(buffer, 0, Math.min(buffer.length, MAX_WIRE + 1 - wire.size()))
    if (count < 0) break
    wire.write(buffer, 0, count)
    assert wire.size() <= MAX_WIRE : 'ANDROID_SECURITY_CONTROL_WIRE_BOUND'
}
def payload = new JsonSlurper().parse(wire.toByteArray(), 'UTF-8')
assert payload instanceof Map && payload.keySet() == (['sourceBase64', 'sha256'] as Set)
assert payload.sourceBase64 instanceof String && payload.sourceBase64.size() <= 43692
assert payload.sha256 instanceof String && payload.sha256 ==~ /[a-f0-9]{64}/
byte[] source = Base64.decoder.decode(payload.sourceBase64)
assert source.length > PREFIX_BYTES && source.length <= MAX_SOURCE
assert Base64.encoder.encodeToString(source) == payload.sourceBase64
assert sha(source) == payload.sha256 : 'ANDROID_SECURITY_CONTROL_SOURCE_HASH'
assert sha(Arrays.copyOfRange(source, 0, PREFIX_BYTES)) == PREFIX_SHA : 'ANDROID_SECURITY_CONTROL_PREFIX_CHANGED'
def decoder = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
String full = decoder.decode(java.nio.ByteBuffer.wrap(source)).toString()
String prefix = new String(Arrays.copyOfRange(source, 0, PREFIX_BYTES), StandardCharsets.UTF_8)
String begin = '// BEGIN CASEOPS ANDROID DEPENDENCY SECURITY'
String end = '// END CASEOPS ANDROID DEPENDENCY SECURITY'
int first = full.indexOf(begin), last = full.indexOf(end)
assert first >= prefix.length() && last > first
assert first == full.lastIndexOf(begin) && last == full.lastIndexOf(end)
assert full.substring(prefix.length(), first).trim().empty
assert full.substring(last + end.length()).trim().empty
String block = full.substring(first, last + end.length())
assert !(block =~ /\b(?:ProcessBuilder|URL|URLConnection|HttpClient|Socket|ServerSocket|File|Files|ClassLoader|GroovyShell|System)\b/).find()
assert !(block =~ /\bRuntime\s*\./).find()
assert !(block =~ /\.(?:execute|exec|evaluate|newInstance|forName|toURL|openConnection)\s*\(/).find()
def constructors = (block =~ /\bnew\s+([A-Za-z_$][A-Za-z0-9_.$]*)/).collect { it[1] }
assert constructors == ['org.gradle.api.GradleException']

def gradleContract = new GradleContract()
def shell = new GroovyShell(this.class.classLoader, new Binding([gradle: gradleContract]))
shell.evaluate(block, 'verified-android-dependency-security-contract.groovy')
Class policy = shell.classLoader.loadClass('CaseOpsAndroidDependencySecurity')
assert gradleContract.settingsHooks.size() == 1 && gradleContract.projectHooks.size() == 1
final Map<String,String> BUILD = [
    'com.google.guava:guava':'33.8.0-jre', 'org.jetbrains.kotlin:kotlin-gradle-plugin':'2.4.21',
    'org.bouncycastle:bcprov-jdk18on':'1.86', 'org.bouncycastle:bcpkix-jdk18on':'1.86',
    'org.bouncycastle:bcutil-jdk18on':'1.86', 'org.apache.commons:commons-lang3':'3.22.0',
    'org.bitbucket.b_c:jose4j':'0.9.7', 'org.jdom:jdom2':'2.0.6.1']
final Map<String,String> OLD = [
    'com.google.guava:guava':'33.7.1-jre', 'org.jetbrains.kotlin:kotlin-gradle-plugin':'2.4.20',
    'org.bouncycastle:bcprov-jdk18on':'1.85', 'org.bouncycastle:bcpkix-jdk18on':'1.85',
    'org.bouncycastle:bcutil-jdk18on':'1.85', 'org.apache.commons:commons-lang3':'3.17.0',
    'org.bitbucket.b_c:jose4j':'0.9.5', 'org.jdom:jdom2':'2.0.6']
final Map<String,String> NEWER = [
    'com.google.guava:guava':'33.8.1-jre', 'org.jetbrains.kotlin:kotlin-gradle-plugin':'2.4.22',
    'org.bouncycastle:bcprov-jdk18on':'1.87', 'org.bouncycastle:bcpkix-jdk18on':'1.87',
    'org.bouncycastle:bcutil-jdk18on':'1.87', 'org.apache.commons:commons-lang3':'3.23.0',
    'org.bitbucket.b_c:jose4j':'0.9.8', 'org.jdom:jdom2':'2.0.7']
final List<String> KOTLIN_IDS = ['org.jetbrains.kotlin.jvm', 'org.jetbrains.kotlin.android',
    'org.jetbrains.kotlin.multiplatform', 'org.jetbrains.kotlin.kapt',
    'org.jetbrains.kotlin.plugin.serialization', 'org.jetbrains.kotlin.plugin.compose']
def settingsClasspath = {
    def s = new SettingsContract()
    def c = s.buildscript.configurations.add('classpath')
    gradleContract.settings(s)
    c
}
def project = { String path ->
    def p = new ProjectContract(path)
    gradleContract.project(p)
    p
}
def expectSelectorRefusal = { Closure action ->
    boolean rejected = false
    try { action.call() }
    catch (org.gradle.api.GradleException error) {
        assert error.message == 'ANDROID_SECURITY_VERSION_SELECTOR_UNREVIEWED'
        rejected = true
    }
    assert rejected : 'UNREVIEWED_SELECTOR_ACCEPTED'
}
final List<Closure> cases = [
    { // 01: settings-handler repairs are real resolution callbacks, not map-only checks.
        def c = settingsClasspath()
        BUILD.each { key, fixed -> assert c.resolutionStrategy.resolve(key, OLD[key], OLD[key]).selected == [fixed] }
        assert c.resolutionStrategy.resolve('unreviewed:ordinary', '1.0', '1.0').selected.empty
    },
    { // 02: current and newer targets are never downgraded, even if requested is old.
        def c = settingsClasspath()
        BUILD.each { key, fixed ->
            assert c.resolutionStrategy.resolve(key, fixed, fixed).selected.empty
            assert c.resolutionStrategy.resolve(key, OLD[key], NEWER[key]).selected.empty
        }
        assert c.resolutionStrategy.resolve('org.jetbrains.kotlin:kotlin-gradle-plugin', '2.4.22', '2.4.20').selected == ['2.4.21']
    },
    { // 03: numeric ordering and missing trailing zeros are semantic, not lexical.
        assert policy.minimum('3.9.99', '3.10.0') == '3.10.0'
        assert policy.minimum('3.10', '3.10.0') == null
        assert policy.minimum('3.10.0.0', '3.10') == null
        assert policy.minimum('3.11.0', '3.10.99') == null
        assert policy.minimum('33.7.10-jre', '33.7.2-jre') == null
        assert policy.minimum(null, '2.4.21') == '2.4.21'
        assert policy.minimum('', '2.4.21') == '2.4.21'
    },
    { // 04: selectors and unreviewed flavours fail instead of silently choosing.
        ['[1.0,2.0)', '1.+', 'latest.release', '1.2-RC1', '1.2-android', '10000.1', '1', '1.2.3.4.5'].each { value ->
            expectSelectorRefusal { policy.minimum(value, '1.2.1') }
        }
        expectSelectorRefusal { policy.minimum('1.2-jre', '1.2.1') }
        expectSelectorRefusal { policy.minimum('1.2', '1.2.1-jre') }
        expectSelectorRefusal { policy.minimum('1.2', 'invalid') }
        assert policy.minimum('1.2-jre', '1.2.1-jre') == '1.2.1-jre'
    },
    { // 05: callers cannot mutate either reviewed coordinate policy.
        assert policy.BUILD == BUILD && policy.APP == ['com.google.code.gson:gson':'2.15.0', 'commons-io:commons-io':'2.22.0', 'com.squareup.okio:okio':'3.18.2', 'com.squareup.okio:okio-jvm':'3.18.2']
        [policy.BUILD, policy.APP].each { map ->
            def before = new LinkedHashMap(map)
            [{ map.put('unreviewed:insert', '1.0') }, { map.remove(map.keySet().first()) }, { map.clear() }].each { change ->
                boolean rejected = false
                try { change.call() } catch (UnsupportedOperationException expected) { rejected = true }
                assert rejected && map == before
            }
        }
    },
    { // 06: BUILD/APP are separate; only the exact WebView buildscript gets AGP repair.
        def app = project(':app')
        def ordinary = app.buildscript.configurations.add('classpath')
        assert ordinary.resolutionStrategy.resolve('com.android.tools.build:gradle', '9.2.0', '9.2.0').selected.empty
        assert ordinary.resolutionStrategy.resolve('com.google.code.gson:gson', '2.8.8', '2.8.8').selected.empty
        def web = project(':react-native-webview')
        def wc = web.buildscript.configurations.add('classpath')
        assert wc.resolutionStrategy.resolve('com.android.tools.build:gradle', '9.2.0', '9.2.0').selected == ['9.2.1']
        assert wc.resolutionStrategy.resolve('com.android.tools.build:gradle', '9.3.0', '9.3.0').selected.empty
        def nested = project(':react-native-webview:other').buildscript.configurations.add('classpath')
        assert nested.resolutionStrategy.resolve('com.android.tools.build:gradle', '9.2.0', '9.2.0').selected.empty
        assert app.configurations.add('releaseRuntimeClasspath').resolutionStrategy.resolve('org.jetbrains.kotlin:kotlin-gradle-plugin', '2.4.20', '2.4.20').selected.empty
    },
    { // 07: both release paths and flavoured release paths get APP repairs.
        def p = project(':app')
        ['releaseCompileClasspath', 'releaseRuntimeClasspath', 'paidReleaseCompileClasspath', 'freeReleaseRuntimeClasspath', 'ProdRELEASECompileClasspath'].each { name ->
            def c = p.configurations.add(name)
            assert c.resolutionStrategy.resolve('com.google.code.gson:gson', '2.8.8', '2.8.8').selected == ['2.15.0']
            assert c.resolutionStrategy.resolve('commons-io:commons-io', '2.13.0', '2.13.0').selected == ['2.22.0']
            ['com.squareup.okio:okio', 'com.squareup.okio:okio-jvm'].each { key -> assert c.resolutionStrategy.resolve(key, '3.15.0', '3.15.0').selected == ['3.18.2'] }
        }
    },
    { // 08: debug, unit/instrumentation-test and unrelated configurations are excluded.
        def p = project(':app')
        ['debugCompileClasspath', 'debugRuntimeClasspath', 'releaseUnitTestCompileClasspath', 'releaseUnitTestRuntimeClasspath', 'freeReleaseUnitTestCompileClasspath', 'releaseAndroidTestCompileClasspath', 'releaseAnnotationProcessor', 'kspRelease', 'releaseCompileClasspathExtra'].each { name ->
            assert p.configurations.add(name).resolutionStrategy.resolve('com.google.code.gson:gson', '2.8.8', '2.8.8').selected.empty
        }
        assert p.buildscript.configurations.add('releaseRuntimeClasspath').resolutionStrategy.resolve('com.google.guava:guava', '33.7.1-jre', '33.7.1-jre').selected.empty
    },
    { // 09: only the six exact Kotlin plugin IDs participate in plugin resolution.
        def s = new SettingsContract(); gradleContract.settings(s)
        KOTLIN_IDS.each { id -> assert s.pluginManagement.resolutionStrategy.resolve(id, '2.4.20').selected == ['2.4.21'] }
        ['org.jetbrains.kotlin.jvm.extra', 'org.jetbrains.kotlin.plugin.allopen', 'com.android.application', 'org.jetbrains.kotlinx.serialization'].each { id ->
            assert s.pluginManagement.resolutionStrategy.resolve(id, '2.4.20').selected.empty
        }
    },
    { // 10: nullable plugin versions stay untouched; lazy configurations still get hooks.
        def s = new SettingsContract(); gradleContract.settings(s)
        KOTLIN_IDS.each { id ->
            [null, '', '2.4.21', '2.5.0'].each { version -> assert s.pluginManagement.resolutionStrategy.resolve(id, version).selected.empty }
            expectSelectorRefusal { s.pluginManagement.resolutionStrategy.resolve(id, '2.+') }
        }
        def later = s.buildscript.configurations.add('classpath')
        assert later.resolutionStrategy.resolve('org.jetbrains.kotlin:kotlin-gradle-plugin', '2.4.20', null).selected == ['2.4.21']
        def p = project(':app')
        assert p.configurations.add('laterReleaseRuntimeClasspath').resolutionStrategy.resolve('com.google.code.gson:gson', '2.8.8', '2.8.8').selected == ['2.15.0']
    }
]
assert cases.size() == CASE_IDS.size()
def events = []
cases.eachWithIndex { Closure control, int index ->
    try {
        control.call()
        events.add([id: CASE_IDS[index], status: 'passed'])
    } catch (Throwable error) {
        events.add([id: CASE_IDS[index], status: 'failed', errorClass: error.class.name])
    }
}
boolean passed = events.size() == 10 && events.every { it.status == 'passed' }
println JsonOutput.toJson([kind: 'android-dependency-security-gradle-contract-controls-v1', scope: 'api-shaped-gradle-contract-doubles', ids: CASE_IDS, events: events, caseCount: events.size(), passed: passed, sourceSha256: payload.sha256, originalPrefixSha256: PREFIX_SHA, httpCalls: 0, childProcesses: 0, nativeAndroidCases: 0, nativeAcceptance: false, fullSdkResolutionStillRequired: true])
assert passed : 'ANDROID_DEPENDENCY_SECURITY_CONTRACT_CONTROLS_FAILED'
