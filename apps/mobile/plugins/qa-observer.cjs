const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const START = '// BEGIN CaseOps QA observer main witness', END = '// END CaseOps QA observer main witness';
const APP = 'ai.caseops.mobile.dev.localacceptance';
const SOURCE_FILES = ['QaPrivacyReader.java', 'QaPrivacyService.java', 'QaLifecycleWitness.java', 'sidecar/ObserverInstrumentation.java', 'sidecar/AndroidManifest.xml'];
const fields = ['dev','ino','mode','uid','gid','nlink','size','mtimeNs','ctimeNs'];
const fdEqual = (a,b) => fields.every(k=>a[k]===b[k]);
const namedMatchesFd = (named,opened,platform=process.platform) => fields.every(k=>(k==='dev'&&platform==='win32'&&named.dev===0n)||named[k]===opened[k]);
const sameIdentity = (a,b) => ['dev','ino','mode','uid','gid','nlink'].every(k=>a[k]===b[k]);
function parents(file) {
 const rows=[];for(let p=path.dirname(file);;p=path.dirname(p)){const s=fs.lstatSync(p,{bigint:true});assert.ok(s.isDirectory()&&!s.isSymbolicLink(),'QA_OBSERVER_SOURCE_NAMESPACE');rows.push([p,...['dev','ino','mode','uid','gid'].map(k=>String(s[k]))]);if(p===path.dirname(p))break;}return rows;
}
function ownFile(s){assert.ok(s.isFile()&&!s.isSymbolicLink()&&s.nlink===1n,'QA_OBSERVER_OWNED_SOURCE');if(process.getuid)assert.equal(s.uid,BigInt(process.getuid()),'QA_OBSERVER_SOURCE_OWNER');}
function readOpened(fd,size){const raw=Buffer.alloc(Number(size)+1);let offset=0;while(offset<raw.length){const n=fs.readSync(fd,raw,offset,raw.length-offset,null);if(!n)break;offset+=n;}assert.equal(offset,Number(size),'QA_OBSERVER_SOURCE_EXTENT');return raw.subarray(0,offset);}
function withHeld(file,limit,operation,{writable=false,platform=process.platform}={}) {
 assert.ok(path.isAbsolute(file),'QA_OBSERVER_ABSOLUTE_SOURCE_REQUIRED');let fd;
 try{fd=fs.openSync(file,(writable?fs.constants.O_RDWR:fs.constants.O_RDONLY)|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0));}catch(error){if(error.code==='ELOOP')assert.fail('QA_OBSERVER_OWNED_SOURCE');throw error;}
 try{const first=fs.fstatSync(fd,{bigint:true});ownFile(first);assert.ok(first.size>0n&&first.size<=BigInt(limit),'QA_OBSERVER_OWNED_SOURCE');const named=fs.lstatSync(file,{bigint:true});ownFile(named);assert.ok(namedMatchesFd(named,first,platform),'QA_OBSERVER_OWNED_SOURCE');const ns=parents(file);const raw=readOpened(fd,first.size),after=fs.fstatSync(fd,{bigint:true}),finalNamed=fs.lstatSync(file,{bigint:true});
  assert.ok(fdEqual(first,after)&&fdEqual(named,finalNamed)&&namedMatchesFd(finalNamed,after,platform),'QA_OBSERVER_SOURCE_CHANGED');assert.deepEqual(parents(file),ns,'QA_OBSERVER_NAMESPACE_CHANGED');return operation({raw,fd,first,named,namespace:ns});
 }finally{fs.closeSync(fd);}
}
function held(file,limit,platform=process.platform){return withHeld(file,limit,({raw})=>raw,{platform});}
function admittedRoot(root){assert.ok(path.isAbsolute(root)&&path.resolve(root)===root,'QA_OBSERVER_OUTPUT_ROOT');const s=fs.lstatSync(root,{bigint:true});assert.ok(s.isDirectory()&&!s.isSymbolicLink(),'QA_OBSERVER_OUTPUT_ROOT');if(process.getuid)assert.equal(s.uid,BigInt(process.getuid()),'QA_OBSERVER_OUTPUT_OWNER');assert.equal(fs.realpathSync(root),root,'QA_OBSERVER_OUTPUT_ROOT');parents(path.join(root,'owned-child'));return root;}
function scoped(file,root){assert.ok(path.isAbsolute(file)&&path.resolve(file)===file&&file.startsWith(root+path.sep),'QA_OBSERVER_OUTPUT_SCOPE');}
function existingParents(file,root){scoped(file,root);const relative=path.relative(root,path.dirname(file));let current=root;for(const part of relative?relative.split(path.sep):[]){current=path.join(current,part);let state;try{state=fs.lstatSync(current,{bigint:true});}catch(e){if(e.code==='ENOENT')return;throw e;}assert.ok(state.isDirectory()&&!state.isSymbolicLink(),'QA_OBSERVER_OUTPUT_NAMESPACE');if(process.getuid)assert.equal(state.uid,BigInt(process.getuid()),'QA_OBSERVER_OUTPUT_OWNER');}parents(path.join(current,'owned-child'));}
function ensureParents(file,root){scoped(file,root);let current=root;for(const part of path.relative(root,path.dirname(file)).split(path.sep).filter(Boolean)){const parent=current;existingParents(path.join(parent,'owned-child'),root);const ns=parents(path.join(parent,'owned-child'));current=path.join(parent,part);let state;try{state=fs.lstatSync(current,{bigint:true});}catch(e){if(e.code!=='ENOENT')throw e;fs.mkdirSync(current,{mode:0o700});state=fs.lstatSync(current,{bigint:true});}assert.ok(state.isDirectory()&&!state.isSymbolicLink(),'QA_OBSERVER_OUTPUT_NAMESPACE');if(process.getuid)assert.equal(state.uid,BigInt(process.getuid()),'QA_OBSERVER_OUTPUT_OWNER');assert.deepEqual(parents(path.join(parent,'owned-child')),ns,'QA_OBSERVER_OUTPUT_NAMESPACE');}existingParents(file,root);}
function existsNamed(file){try{fs.lstatSync(file);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}}
function knownGenerated(file,raw,root){existingParents(file,root);if(existsNamed(file))assert.ok(held(file,1048576).equals(raw),'QA_OBSERVER_UNOWNED_GENERATED_TARGET');}
function writeGenerated(file,raw,root){knownGenerated(file,raw,root);if(existsNamed(file))return;ensureParents(file,root);const ns=parents(file),fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|(fs.constants.O_NOFOLLOW??0),0o600);
 try{const first=fs.fstatSync(fd,{bigint:true}),initialNamed=fs.lstatSync(file,{bigint:true});ownFile(first);ownFile(initialNamed);assert.ok(namedMatchesFd(initialNamed,first),'QA_OBSERVER_OUTPUT_CHANGED');let offset=0;while(offset<raw.length){const n=fs.writeSync(fd,raw,offset,raw.length-offset,offset);assert.ok(n>0,'QA_OBSERVER_OUTPUT_WRITE');offset+=n;}fs.fsyncSync(fd);const last=fs.fstatSync(fd,{bigint:true}),named=fs.lstatSync(file,{bigint:true});assert.ok(sameIdentity(first,last)&&sameIdentity(initialNamed,named)&&last.size===BigInt(raw.length)&&fdEqual(last,fs.fstatSync(fd,{bigint:true}))&&namedMatchesFd(named,last),'QA_OBSERVER_OUTPUT_CHANGED');assert.deepEqual(parents(file),ns,'QA_OBSERVER_OUTPUT_NAMESPACE');}finally{fs.closeSync(fd);}}
function removeGenerated(file,raw,root){existingParents(file,root);if(!existsNamed(file))return;withHeld(file,1048576,({raw:actual,fd,first,named,namespace:ns})=>{assert.ok(actual.equals(raw),'QA_OBSERVER_UNOWNED_GENERATED_TARGET');assert.ok(fdEqual(named,fs.lstatSync(file,{bigint:true}))&&fdEqual(first,fs.fstatSync(fd,{bigint:true})),'QA_OBSERVER_OUTPUT_CHANGED');assert.deepEqual(parents(file),ns,'QA_OBSERVER_OUTPUT_NAMESPACE');fs.unlinkSync(file);assert.equal(existsNamed(file),false,'QA_OBSERVER_OUTPUT_ABSENCE');assert.deepEqual(parents(file),ns,'QA_OBSERVER_OUTPUT_NAMESPACE');});}
function transformOwned(file,original,replacement,root){existingParents(file,root);withHeld(file,1048576,({raw,fd,first,named,namespace:ns})=>{assert.ok(raw.equals(original),'QA_OBSERVER_SOURCE_CHANGED');if(raw.equals(replacement))return;assert.ok(fdEqual(first,fs.fstatSync(fd,{bigint:true}))&&fdEqual(named,fs.lstatSync(file,{bigint:true})),'QA_OBSERVER_SOURCE_CHANGED');assert.deepEqual(parents(file),ns,'QA_OBSERVER_NAMESPACE_CHANGED');let offset=0;while(offset<replacement.length){const n=fs.writeSync(fd,replacement,offset,replacement.length-offset,offset);assert.ok(n>0,'QA_OBSERVER_OUTPUT_WRITE');offset+=n;}fs.ftruncateSync(fd,replacement.length);fs.fsyncSync(fd);const last=fs.fstatSync(fd,{bigint:true}),afterNamed=fs.lstatSync(file,{bigint:true});assert.ok(sameIdentity(first,last)&&sameIdentity(named,afterNamed)&&last.size===BigInt(replacement.length)&&fdEqual(last,fs.fstatSync(fd,{bigint:true}))&&namedMatchesFd(afterNamed,last),'QA_OBSERVER_OUTPUT_CHANGED');assert.deepEqual(parents(file),ns,'QA_OBSERVER_NAMESPACE_CHANGED');},{writable:true});}

function settings(env, profile) {
  const selected = env.CASEOPS_MOBILE_ANDROID_PRIVACY_OBSERVER;
  const configured = env.CASEOPS_ANDROID_OBSERVER_PYTHON || env.CASEOPS_ANDROID_OBSERVER_PYTHON_SHA256 || env.CASEOPS_ANDROID_OBSERVER_ADMISSION;
  if (selected === undefined) { assert.ok(!configured, 'QA_OBSERVER_RUNTIME_REQUIRES_EXPLICIT_MODE'); return null; }
  assert.equal(selected,'1','QA_OBSERVER_EXPLICIT_MODE_REQUIRED'); assert.equal(profile,'android-local-acceptance','QA_OBSERVER_ANDROID_QA_ONLY');
  assert.match(env.CASEOPS_ANDROID_OBSERVER_PYTHON_SHA256 || '', /^[a-f0-9]{64}$/, 'QA_OBSERVER_PINNED_PYTHON_REQUIRED');
  if (env.CASEOPS_ANDROID_OBSERVER_ADMISSION !== undefined) {
    assert.ok(Buffer.byteLength(env.CASEOPS_ANDROID_OBSERVER_ADMISSION)<=4096,'QA_OBSERVER_OWNER_ENVELOPE_BOUND');const admission=JSON.parse(env.CASEOPS_ANDROID_OBSERVER_ADMISSION);
    assert.deepEqual(Object.keys(admission).sort(),['path','sha256','sizeBytes']);assert.ok(path.isAbsolute(admission.path)&&path.resolve(admission.path)===admission.path&&!admission.path.includes('\0'),'QA_OBSERVER_OWNER_REQUEST_PATH');assert.match(admission.sha256,/^[a-f0-9]{64}$/);assert.ok(Number.isSafeInteger(admission.sizeBytes)&&admission.sizeBytes>0&&admission.sizeBytes<=16384,'QA_OBSERVER_OWNER_REQUEST_EXTENT');
  }
  const python = env.CASEOPS_ANDROID_OBSERVER_PYTHON; const bytes = held(python,33554432); assert.equal(createHash('sha256').update(bytes).digest('hex'),env.CASEOPS_ANDROID_OBSERVER_PYTHON_SHA256,'QA_OBSERVER_PYTHON_HASH');
  return { python, pythonSha256: env.CASEOPS_ANDROID_OBSERVER_PYTHON_SHA256 };
}
function updateMainApplication(source, enabled) {
  const block = `${START}\nopen class MainApplication : Application(), ReactApplication {\n${END}`;
  const original = 'class MainApplication : Application(), ReactApplication {';
  if (source.includes(START) || source.includes(END)) { assert.equal(source.split(block).length,2,'QA_OBSERVER_MAIN_MARKER'); source=source.replace(block,original); }
  assert.equal(source.split(original).length,2,'QA_OBSERVER_REVIEWED_MAIN_APPLICATION');
  return enabled ? source.replace(original,block) : source;
}
// Source is read through one descriptor before compilation in the explicitly
// pinned Python. The outer build owner separately binds runtime/helpers/PIDs.
const BOOT = String.raw`import os,stat,sys,hashlib,pathlib,time
started=time.monotonic()
p=pathlib.Path(sys.argv[1]); expected=sys.argv[2]; args=sys.argv[3:]
def ident(s):return tuple(getattr(s,k)for k in('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'))
def named_matches_fd(named,opened,platform=os.name):return all(getattr(named,k)==getattr(opened,k)for k in('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')if not(k=='st_dev'and platform=='nt'and named.st_dev==0))
fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
try:
 s=os.fstat(fd);assert stat.S_ISREG(s.st_mode)and s.st_nlink==1 and s.st_uid==(os.getuid()if hasattr(os,'getuid')else pathlib.Path.home().stat().st_uid)and s.st_size<=65536,'QA_OBSERVER_HELPER_OWNER'
 n=p.lstat();assert stat.S_ISREG(n.st_mode)and not stat.S_ISLNK(n.st_mode)and n.st_nlink==1 and named_matches_fd(n,s),'QA_OBSERVER_HELPER_OWNER'
 ns=[(str(a),a.lstat().st_dev,a.lstat().st_ino,a.lstat().st_mode,a.lstat().st_uid,a.lstat().st_gid)for a in p.parents]
 assert all(stat.S_ISDIR(a.lstat().st_mode)and not stat.S_ISLNK(a.lstat().st_mode)for a in p.parents),'QA_OBSERVER_HELPER_NAMESPACE'
 raw=bytearray()
 while len(raw)<=s.st_size:
  part=os.read(fd,min(65536,s.st_size+1-len(raw)))
  if not part:break
  raw.extend(part)
 last=os.fstat(fd);named_after=p.lstat()
 assert len(raw)==s.st_size and ident(s)==ident(last)and ident(n)==ident(named_after)and named_matches_fd(named_after,last)and ns==[(str(a),a.lstat().st_dev,a.lstat().st_ino,a.lstat().st_mode,a.lstat().st_uid,a.lstat().st_gid)for a in p.parents]and hashlib.sha256(raw).hexdigest()==expected,'QA_OBSERVER_HELPER_CHANGED'
finally:os.close(fd)
sys.argv=[str(p)]+args
exec(compile(raw,str(p),'exec'),{'__name__':'__main__','__file__':str(p),'_CASEOPS_OBSERVER_STARTED_MONOTONIC':started,'_CASEOPS_OBSERVER_HELPER_SHA256':expected})`;
function gradle(settings, sourceRoot, sourceSha, helperSha256) {
  const q = v => JSON.stringify(v);
  const generated = `app/build/generated/caseops-qa-observer/${sourceSha}/localAcceptance`;
  return `
abstract class CaseOpsQaObserverManifest extends org.gradle.api.DefaultTask {
 @javax.inject.Inject abstract org.gradle.process.ExecOperations getExecOperations()
 @org.gradle.api.tasks.InputFile @org.gradle.api.tasks.PathSensitive(org.gradle.api.tasks.PathSensitivity.NONE)
 abstract org.gradle.api.file.RegularFileProperty getInputManifest()
 @org.gradle.api.tasks.OutputFile abstract org.gradle.api.file.RegularFileProperty getOutputManifest()
 @org.gradle.api.tasks.OutputFile abstract org.gradle.api.file.RegularFileProperty getReceiptFile()
 @org.gradle.api.tasks.OutputDirectory abstract org.gradle.api.file.DirectoryProperty getOutputJava()
 @org.gradle.api.tasks.TaskAction void transformManifest() {
  if (System.getenv('CASEOPS_ANDROID_OBSERVER_PYTHON') != ${q(settings.python)} || System.getenv('CASEOPS_ANDROID_OBSERVER_PYTHON_SHA256') != ${q(settings.pythonSha256)}) throw new GradleException('QA_OBSERVER_RUNTIME_CHANGED')
  execOperations.exec { workingDir project.rootProject.projectDir; commandLine ${q(settings.python)}, '-I', '-B', '-c', ${q(BOOT)}, ${q(path.join(sourceRoot,'scripts/mobile/android-observer-manifest.py'))}, ${q(helperSha256)}, '--input', inputManifest.get().asFile.absolutePath, '--output-root', project.rootProject.file(${q(generated)}).absolutePath, '--manifest-output', outputManifest.get().asFile.absolutePath, '--android-root', project.rootProject.projectDir.absolutePath, '--source', ${q(sourceSha)}, '--target', ${q(APP)}, '--python-sha256', ${q(settings.pythonSha256)}; if(System.getenv('CASEOPS_ANDROID_OBSERVER_ADMISSION')!=null) environment 'CASEOPS_ANDROID_OBSERVER_ADMISSION', System.getenv('CASEOPS_ANDROID_OBSERVER_ADMISSION') }
 }
}
androidComponents.onVariants(androidComponents.selector().withBuildType('localAcceptance')) { variant ->
 def observerTask = tasks.register('caseopsQaObserverManifest', CaseOpsQaObserverManifest) {
  outputJava.set(rootProject.layout.projectDirectory.dir(${q(generated+'/java/ai/caseops/mobile/qa')}))
  receiptFile.set(rootProject.layout.projectDirectory.file(${q(generated+'/receipt.json')}))
 }
 variant.artifacts.use(observerTask).wiredWithFiles({ it.inputManifest }, { it.outputManifest }).toTransform(com.android.build.api.artifact.SingleArtifact.MERGED_MANIFEST.INSTANCE)
 variant.sources.java.addGeneratedSourceDirectory(observerTask, { it.outputJava })
}
tasks.matching { it.name == 'assembleLocalAcceptance' }.configureEach { dependsOn ':caseopsPrivacyObserver:assembleRelease' }
`;
}
function overlay(androidRoot,sourceRoot,configuration,sourceSha) {
 androidRoot=admittedRoot(androidRoot);const javaRoot=path.join(androidRoot,'app/src/localAcceptance/java/ai/caseops/mobile/qa'),sidecar=path.join(androidRoot,'caseopsPrivacyObserver');
 const optional=(file,limit)=>{existingParents(file,androidRoot);try{fs.lstatSync(file);}catch(e){if(e.code==='ENOENT')return null;throw e;}return held(file,limit);};
 const main=path.join(androidRoot,'app/src/main/java/ai/caseops/mobile/dev/MainApplication.kt'),originalMain=configuration?held(main,65536):optional(main,65536);
 const markedMain=originalMain&&(originalMain.includes(START)||originalMain.includes(END));
 const updatedMain=originalMain&&(configuration||markedMain)?Buffer.from(updateMainApplication(originalMain.toString('utf8'),Boolean(configuration))):originalMain;
 const settingsFile=path.join(androidRoot,'settings.gradle'),originalSettings=configuration?held(settingsFile,1048576):optional(settingsFile,1048576),include="\n// CaseOps QA observer module\ninclude ':caseopsPrivacyObserver'\n";let raw=originalSettings?.toString('utf8')||'';assert.ok(raw.split(include).length<=2,'QA_OBSERVER_SETTINGS_MARKER');raw=raw.replace(include,'');assert.equal(raw.includes('caseopsPrivacyObserver'),false,'QA_OBSERVER_UNOWNED_MODULE_REFERENCE');if(configuration)raw+=include;const updatedSettings=originalSettings===null?null:Buffer.from(raw);
 const mapping=new Map(SOURCE_FILES.map(name=>[path.join(sourceRoot,'apps/mobile/qa-observer',name),name.startsWith('sidecar/')?path.join(sidecar,'src/main',name.endsWith('.java')?'java/ai/caseops/qa/privacyobserver/ObserverInstrumentation.java':'AndroidManifest.xml'):path.join(javaRoot,name)]));
 const selected=[...mapping].filter(([,target])=>{existingParents(target,androidRoot);if(configuration)return true;try{fs.lstatSync(target);return true;}catch(e){if(e.code==='ENOENT')return false;throw e;}});
 const outputs=selected.map(([source,target])=>[target,held(source,65536)]);
 const sidecarGradle=path.join(sidecar,'build.gradle');existingParents(sidecarGradle,androidRoot);let hasGradle=Boolean(configuration);if(!hasGradle){try{fs.lstatSync(sidecarGradle);hasGradle=true;}catch(e){if(e.code!=='ENOENT')throw e;}}
 if(hasGradle)outputs.push([sidecarGradle,Buffer.from(`apply plugin: 'com.android.application'\nandroid { namespace 'ai.caseops.qa.privacyobserver'; compileSdk rootProject.ext.compileSdkVersion\n defaultConfig { applicationId 'ai.caseops.qa.privacyobserver'; minSdk 31; targetSdk rootProject.ext.targetSdkVersion; versionCode 1; versionName '1' }\n signingConfigs { observerQa { def original=project(':app').android.signingConfigs.debug; storeFile original.storeFile; storePassword original.storePassword; keyAlias original.keyAlias; keyPassword original.keyPassword } }\n buildTypes { release { debuggable false; signingConfig signingConfigs.observerQa; minifyEnabled false } }\n}\n`)]);
 // Every existing target is admitted before any mkdir/write/unlink. Unknown
 // bytes, links or owners stay untouched even during production cleanup.
 for(const[target,bytes]of outputs)knownGenerated(target,bytes,androidRoot);if(originalMain)existingParents(main,androidRoot);if(originalSettings)existingParents(settingsFile,androidRoot);
 if(configuration)for(const[target,bytes]of outputs)writeGenerated(target,bytes,androidRoot);
 if(originalMain&&updatedMain&&!originalMain.equals(updatedMain))transformOwned(main,originalMain,updatedMain,androidRoot);if(originalSettings&&updatedSettings&&!originalSettings.equals(updatedSettings))transformOwned(settingsFile,originalSettings,updatedSettings,androidRoot);
 if(!configuration)for(const[target,bytes]of outputs)removeGenerated(target,bytes,androidRoot);
}

module.exports={fdEqual,namedMatchesFd,settings,held,updateMainApplication,gradle,overlay,SOURCE_FILES,BOOT};
