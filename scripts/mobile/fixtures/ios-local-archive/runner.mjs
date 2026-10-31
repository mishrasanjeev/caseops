import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import cp from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
import { pathToFileURL } from 'node:url';
export const archiveControlCases = Object.freeze(["ARCHIVE-01-absent-and-empty-targets","ARCHIVE-02-original-filesystem-archive","ARCHIVE-03-unsafe-uri-and-argv","ARCHIVE-04-changed-manifest-and-archive","ARCHIVE-05-source-replacement-keeps-reviewed-bytes","ARCHIVE-06-target-link-content-and-replacement","ARCHIVE-07-original-write-error-identity","ARCHIVE-08-https-path-and-marker-unchanged"]);
const hash = b => createHash('sha256').update(b).digest('hex');
const sourceOpenCanRead = flags => typeof flags === 'number' ? (flags & 3) !== fs.constants.O_WRONLY : !['w','wx','xw','a','ax','xa','as','sa'].includes(flags);
const frame = s => ['dev','ino','mode','uid','gid','nlink','size','mtimeNs','ctimeNs'].map(k => String(s[k]));
function held(ref) {
  const fd = fs.openSync(ref.path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const before = fs.fstatSync(fd, { bigint: true }), named = fs.lstatSync(ref.path, { bigint: true });
    assert.ok(before.isFile() && !named.isSymbolicLink() && before.uid === BigInt(process.getuid()) && before.nlink === 1n && (before.mode & 0o022n) === 0n);
    assert.deepEqual(frame(before), frame(named)); assert.equal(before.size, BigInt(ref.sizeBytes));
    assert.ok(ref.sizeBytes > 0 && ref.sizeBytes <= 33554432 && fs.realpathSync(ref.path) === ref.path);
    const bytes = Buffer.alloc(ref.sizeBytes + 1); let n = 0;
    while (n < bytes.length) { const read = fs.readSync(fd, bytes, n, Math.min(65536, bytes.length - n), null); if (!read) break; n += read; }
    assert.equal(n, ref.sizeBytes); assert.equal(hash(bytes.subarray(0,n)), ref.sha256);
    assert.deepEqual(frame(before), frame(fs.fstatSync(fd,{bigint:true}))); assert.deepEqual(frame(before), frame(fs.lstatSync(ref.path,{bigint:true})));
    return bytes.subarray(0,n);
  } finally { fs.closeSync(fd); }
}
const [mode, file, pin, size] = process.argv.slice(2);
if (mode === '--list') {
  assert.equal(process.argv.length,3); console.log(JSON.stringify({ profile:'ios-sdk-local-archive-controls-v1', cases:archiveControlCases, phases:24, nativeAcceptance:false }));
} else {
  assert.ok(mode === '--run' && process.argv.length === 6 && process.platform === 'darwin' && process.versions.node === '24.15.0');
  const configBytes = held({path:file,sha256:pin,sizeBytes:Number(size)}), q = JSON.parse(configBytes); configBytes.fill(0);
  assert.equal(q.kind,'ios-sdk-local-archive-controls-v1'); assert.equal(path.dirname(q.sourceRoot),q.outputRoot); assert.equal(path.dirname(q.policyDirectory),q.outputRoot);
  const code = held(q.helper), m = await import('data:text/javascript;base64,' + code.toString('base64')); code.fill(0);
  const prepared = await m.prepareIosHostLaunch({directory:q.policyDirectory,nodePolicy:q.nodePolicy,rubyBundle:q.rubyBundle,tools:q.tools,role:'base',deadline:q.deadlineEpochMs,sourceRoot:q.sourceRoot});
  const scoped = await m.composeIosHostCommand(prepared.policyRef,'neutral',[],{environment:{CASEOPS_IOS_HOST_OUTER_DEADLINE:String(q.deadlineEpochMs)},end:Date.now()+20000});
  const originalEnvironment = {...process.env};
  function environment(value) { for (const key of Object.keys(process.env)) delete process.env[key]; Object.assign(process.env,value); }
  const journal = fs.openSync(path.join(q.outputRoot,'events.jsonl'),fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_WRONLY,0o600);
  const write = value => fs.writeSync(journal,JSON.stringify(value)+'\n');
  const originals = {open:fs.openSync,read:fs.readSync,write:fs.writeSync,spawn:cp.spawn};
  const ordinarySpawnError = new Error('CONTROL_HTTP_SPAWN_STOP'); let spawns=0,actualCli=0,sequence=0;
  cp.spawn = (file,args,options) => { spawns++; throw ordinarySpawnError; }; syncBuiltinESMExports();
  const sourceA=path.join(q.sourceRoot,q.smallest.path),sourceB=path.join(q.sourceRoot,q.original.path);
  const bytesA=held({path:sourceA,sha256:q.smallest.sha256,sizeBytes:q.smallest.sizeBytes}),bytesB=held({path:sourceB,sha256:q.original.sha256,sizeBytes:q.original.sizeBytes});
  const manifestPath=path.join(q.sourceRoot,'apps/mobile/'+q.smallest.packageRelative+'/package.json'),manifestBytes=fs.readFileSync(manifestPath);
  const output = label => {const dir=path.join(prepared.policy.paths.temporary,'d20300101-1000-'+label);fs.mkdirSync(dir,{mode:0o700});return path.join(dir,'file.tgz');};
  const argsFor = (source,target) => ['-f','-L','-o',target,pathToFileURL(source).href,'--create-dirs','--netrc-optional','--retry','2',"-A 'CocoaPods/1.17.0 cocoapods-downloader/2.1'"];
  async function call(args) {environment({...scoped.environment,...scoped.node.environment});actualCli++;let value,error;try{value=await m.iosHostCli(['curl',...args]);}catch(e){error=e;}finally{fs.openSync=originals.open;fs.readSync=originals.read;fs.writeSync=originals.write;}return {value,error};}
  const refused = result => { assert.ok(result.error); assert.equal(result.value,undefined); };
  const tests = [
    async()=>{for(const existing of [false,true]){const target=output('a'+(++sequence));if(existing)fs.writeFileSync(target,'',{mode:0o600,flag:'wx'});const before=spawns;let sourceOpens=0,targetFd,writeBuffer;fs.openSync=(p,...rest)=>{const fd=originals.open(p,...rest);if(p===sourceA)sourceOpens++;if(p===target)targetFd=fd;return fd;};fs.writeSync=(fd,b,...rest)=>{if(fd===targetFd)writeBuffer=b;return originals.write(fd,b,...rest);};const r=await call(argsFor(sourceA,target));assert.equal(r.error,undefined);assert.equal(r.value,0);assert.equal(spawns,before);assert.equal(sourceOpens,1);assert.equal(hash(fs.readFileSync(target)),q.smallest.sha256);assert.ok(writeBuffer.every(x=>x===0));assert.throws(()=>fs.fstatSync(targetFd),{code:'EBADF'});}},
    async()=>{const target=output('original'),before=spawns,r=await call(argsFor(sourceB,target));assert.equal(r.error,undefined);assert.equal(r.value,0);assert.equal(hash(fs.readFileSync(target)),q.original.sha256);assert.equal(spawns,before);},
    async()=>{const good=argsFor(sourceA,output('pure')),changes=[a=>{a[4]=a[4].replace('file:///','file://remote/');},a=>{a[4]=a[4].replace('file:///','file://localhost/');},a=>{a[4]=a[4].replace('/prebuilds/','/%70rebuilds/');},a=>{a[4]=a[4].replace('/release/','/other/../release/');},a=>{a[4]+='?query=1';},a=>{a[4]+='#fragment';},a=>{a[4]=a[4].replace('.tar.gz','Other.tar.gz');},a=>{a[1]='--location';},a=>{a.push('-H','Authorization: SYNTHETIC');}];for(const change of changes){const a=[...good];change(a);let error;try{m.validateIosLocalArchiveArguments(a,q.sourceRoot);}catch(e){error=e;}assert.ok(error);}const projected=m.validateIosLocalArchiveArguments(good,q.sourceRoot);assert.ok(Object.isFrozen(projected.archive));assert.deepEqual(projected.args,good);},
    async()=>{for(const [p,b]of [[manifestPath,manifestBytes],[sourceA,bytesA]]){const target=output('changed'+(++sequence)),before=spawns;try{fs.writeFileSync(p,Buffer.from('CHANGED'));const r=await call(argsFor(sourceA,target));refused(r);assert.equal(fs.existsSync(target),false);assert.equal(spawns,before);}finally{fs.writeFileSync(p,b,{mode:0o600});}}},
    async()=>{for(const [flags,expected]of [[fs.constants.O_RDONLY,true],[fs.constants.O_RDWR,true],[fs.constants.O_WRONLY,false],['r',true],['r+',true],['w+',true],['wx',false]])assert.equal(sourceOpenCanRead(flags),expected);for(const during of [false,true]){const target=output('source'+(++sequence)),backup=sourceA+'.retained';let changed=false,sourceOpens=0,targetFd,writeBuffer;const replace=()=>{fs.renameSync(sourceA,backup);fs.writeFileSync(sourceA,'UNREVIEWED_REPLACEMENT',{mode:0o600,flag:'wx'});changed=true;};fs.openSync=(p,...rest)=>{const fd=originals.open(p,...rest);if(p===sourceA&&sourceOpenCanRead(rest[0]))sourceOpens++;if(p===target){targetFd=fd;if(!during)replace();}return fd;};fs.writeSync=(fd,b,...rest)=>{if(fd===targetFd){writeBuffer=b;if(during&&!changed)replace();}return originals.write(fd,b,...rest);};let r;try{r=await call(argsFor(sourceA,target));refused(r);assert.match(r.error.message,/IOS_HOST_LOCAL_ARCHIVE_SOURCE/);assert.equal(sourceOpens,1);if(during){assert.equal(hash(fs.readFileSync(target)),q.smallest.sha256);assert.ok(writeBuffer.every(x=>x===0));}else assert.equal(fs.statSync(target).size,0);}finally{fs.openSync=originals.open;fs.readSync=originals.read;fs.writeSync=originals.write;if(changed){assert.equal(fs.readFileSync(sourceA,'utf8'),'UNREVIEWED_REPLACEMENT');fs.unlinkSync(sourceA);fs.renameSync(backup,sourceA);}}}},
    async()=>{for(const kind of ['nonempty','symlink','hardlink','replacement']){const target=output(kind),sentinel=target+'.sentinel';let opened;fs.writeFileSync(sentinel,'SYNTHETIC_SENTINEL',{mode:0o600,flag:'wx'});if(kind==='nonempty')fs.writeFileSync(target,'KEPT',{mode:0o600,flag:'wx'});if(kind==='symlink')fs.symlinkSync(sentinel,target);if(kind==='hardlink'){fs.writeFileSync(target,'',{mode:0o600,flag:'wx'});fs.linkSync(target,target+'.second');}if(kind==='replacement')fs.openSync=(p,...rest)=>{const fd=originals.open(p,...rest);if(p===target&&opened===undefined){opened=fd;fs.renameSync(target,target+'.retained');fs.writeFileSync(target,'NEW_NAME_BYTES',{mode:0o600,flag:'wx'});}return fd;};try{const before=spawns,r=await call(argsFor(sourceA,target));refused(r);assert.equal(spawns,before);assert.equal(fs.readFileSync(sentinel,'utf8'),'SYNTHETIC_SENTINEL');if(kind==='nonempty')assert.equal(fs.readFileSync(target,'utf8'),'KEPT');if(kind==='replacement'){assert.equal(fs.readFileSync(target,'utf8'),'NEW_NAME_BYTES');assert.equal(fs.statSync(target+'.retained').size,0);assert.throws(()=>fs.fstatSync(opened),{code:'EBADF'});}}finally{fs.openSync=originals.open;if(kind==='symlink'){assert.ok(fs.lstatSync(target).isSymbolicLink());fs.unlinkSync(target);}if(kind==='hardlink'){assert.equal(fs.statSync(target).ino,fs.statSync(target+'.second').ino);fs.unlinkSync(target+'.second');}}}},
    async()=>{const target=output('error'),sentinel=new Error('CONTROL_ORIGINAL_WRITE_ERROR');let fd;fs.openSync=(p,...rest)=>{const f=originals.open(p,...rest);if(p===target)fd=f;return f;};fs.writeSync=(f,...rest)=>{if(f===fd)throw sentinel;return originals.write(f,...rest);};const r=await call(argsFor(sourceA,target));assert.equal(r.error,sentinel);assert.throws(()=>fs.fstatSync(fd),{code:'EBADF'});},
    async()=>{const target=output('https'),a=argsFor(sourceA,target);a[4]='https://packages.contract-fixture.org/public.tgz';const before=spawns,r=await call(a);assert.equal(r.error,ordinarySpawnError);assert.equal(spawns,before+1);assert.equal(fs.existsSync(target),false);}
  ];
  let failed=0;
  try{for(let i=0;i<tests.length;i++){const id=archiveControlCases[i];write({id,phase:'setup',status:'passed'});let error;try{await tests[i]();}catch(e){error=e;failed++;}finally{fs.openSync=originals.open;fs.readSync=originals.read;fs.writeSync=originals.write;}write({id,phase:'call',status:error?'failed':'passed',code:error?(/^IOS_HOST_[A-Z0-9_]+$/.test(error.message)?error.message:'CONTROL_ASSERTION_FAILED'):null});write({id,phase:'teardown',status:'passed'});}write({type:'completed',cases:8,phases:24,failed,actualCliInvocations:actualCli,childSpawnAttempts:spawns,actualChildren:0,httpRequests:0,nativeAcceptance:false});}
  finally{cp.spawn=originals.spawn;syncBuiltinESMExports();environment(originalEnvironment);bytesA.fill(0);bytesB.fill(0);manifestBytes.fill(0);fs.closeSync(journal);}
  console.log(JSON.stringify({profile:'ios-sdk-local-archive-controls-v1',cases:8,phases:24,failed,actualCliInvocations:actualCli,actualChildren:0,httpRequests:0,nativeAcceptance:false}));process.exitCode=failed?1:0;
}
