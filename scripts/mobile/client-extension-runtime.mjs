import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readClientPublicInput, assertClientNamedDescriptor } from './client-extension-public-input.mjs';

const fields=['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'];
const meta=s=>Object.fromEntries(fields.map(k=>[k,String(s[k])]));
const sha=b=>createHash('sha256').update(b).digest('hex');
function canonicalParents(file) {
  assert.equal(fs.realpathSync(file),file,'CX_CANONICAL_RUNTIME_NAMESPACE_REQUIRED');const result=[];
  for(let parent=path.dirname(file);;parent=path.dirname(parent)){
    const value=fs.lstatSync(parent,{bigint:true});assert.ok(value.isDirectory()&&!value.isSymbolicLink());
    result.push([parent,...['dev','ino','uid','gid','mode'].map(k=>String(value[k]))]);
    if(path.dirname(parent)===parent)return result;
  }
}
export function selectedClientExecutable(name,environment=process.env) {
  assert.ok(['git','node'].includes(name));
  const leaf=process.platform==='win32'?name+'.exe':name;
  for(const folder of(environment.PATH||'').split(path.delimiter))if(path.isAbsolute(folder)){
    const file=path.join(folder,leaf);try{fs.accessSync(file,fs.constants.X_OK);if(fs.statSync(file).isFile())return fs.realpathSync(file);}catch{}
  }
  throw Error('CX_ACCEPTED_EXECUTABLE_NOT_ON_PATH');
}
function admitOpenedRegular(opened, maxBytes) {
  assert.ok(opened.isFile() && opened.nlink === 1n && opened.size <= BigInt(maxBytes), 'CX_COMPLETE_TREE_BYTE_BOUND');
  if (typeof process.getuid === 'function') assert.equal(opened.uid, BigInt(process.getuid()));
}
function readOpenedFile(file, fd, opened, maxBytes, check = () => {}) {
  admitOpenedRegular(opened, maxBytes);
  const named = fs.lstatSync(file, { bigint: true });
  assert.ok(named.isFile() && !named.isSymbolicLink());
  assertClientNamedDescriptor(named, opened);
  const parents = canonicalParents(file), hash = createHash('sha256'), buffer = Buffer.alloc(65536);
  let bytes = 0;
  while (bytes <= maxBytes) {
    check();
    const n = fs.readSync(fd, buffer, 0, Math.min(buffer.length, maxBytes + 1 - bytes), null);
    if (!n) break;
    bytes += n; assert.ok(bytes <= maxBytes, 'CX_COMPLETE_TREE_BYTE_BOUND'); hash.update(buffer.subarray(0,n));
  }
  assert.equal(BigInt(bytes), opened.size);
  assert.deepEqual(meta(fs.fstatSync(fd, {bigint:true})), meta(opened));
  const finalNamed = fs.lstatSync(file, {bigint:true});
  assert.deepEqual(meta(finalNamed), meta(named)); assertClientNamedDescriptor(finalNamed, opened);
  assert.deepEqual(canonicalParents(file), parents);
  return {path:file, sha256:hash.digest('hex'), extent:bytes, metadata:meta(opened), namedMetadata:meta(named), parents};
}
export function captureClientFile(file,maxBytes=268435456) {
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 268435456);
  let fd;
  try {
    fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
    const opened = fs.fstatSync(fd, {bigint:true});
    const value = readOpenedFile(file, fd, opened, maxBytes);
    return {path:file,sha256:value.sha256,extent:value.extent,metadata:value.metadata};
  } finally { if (fd !== undefined) fs.closeSync(fd); }
}

/** Receipt v2 requires a fresh capture; legacy one-observation receipts are not upgraded.
 * bytes remains logical payload size. chargedBytes/chargedEntries account for both
 * complete observations under one budget; internal links are never traversed. */
export function captureClientTree(root,{maxEntries=50000,maxBytes=536870912,timeoutMs=5000}={}) {
  assert.ok(Number.isSafeInteger(maxEntries) && maxEntries > 0 && maxEntries <= 50000);
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 536870912);
  assert.ok(Number.isSafeInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 5000);
  assert.equal(path.resolve(root),root); assert.equal(fs.realpathSync(root),root);
  const deadline = performance.now()+timeoutMs; let charged=0,bytes=0;
  const check=()=>assert.ok(performance.now()<deadline,'CX_COMPLETE_TREE_DEADLINE');
  const charge=()=>{check();assert.ok(charged<maxEntries,'CX_COMPLETE_TREE_ENTRY_BOUND');charged++;};
  function inventory() {
    const rows=[],states=new Map(),scheduled=new Set(),todo=[];
    const schedule=file=>{assert.ok(!scheduled.has(file),'CX_DUPLICATE_TREE_ENTRY');charge();scheduled.add(file);todo.push(file);};
    schedule(root);
    while(todo.length) {
      check();const file=todo.pop(),relative=path.relative(root,file);let fd,opened,named;
      try {
        try {
          fd=fs.openSync(file,fs.constants.O_RDONLY|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0));
          opened=fs.fstatSync(fd,{bigint:true});
          if(file===root)assert.ok(opened.isDirectory(),'CX_TREE_ROOT_DIRECTORY_REQUIRED');
          if(opened.isFile())admitOpenedRegular(opened,maxBytes);
          named=fs.lstatSync(file,{bigint:true});
        } catch(error) {
          if(fd!==undefined)throw error;
          named=fs.lstatSync(file,{bigint:true});
          const directoryFallback=process.platform==='win32'&&named.isDirectory()&&['EISDIR','EPERM'].includes(error.code);
          if(!named.isSymbolicLink()&&!directoryFallback)throw error;
        }
        if(file===root)assert.ok(named.isDirectory()&&!named.isSymbolicLink(),'CX_TREE_ROOT_DIRECTORY_REQUIRED');
        if(typeof process.getuid==='function')assert.equal(named.uid,BigInt(process.getuid()));
        let row;
        if(named.isSymbolicLink()) {
          const target=fs.readlinkSync(file),real=fs.realpathSync(file);
          assert.ok(real===root||real.startsWith(root+path.sep),'CX_EXTERNAL_TOOL_SYMLINK');
          row={path:relative,kind:'symlink',metadata:meta(named),target};
        } else if(named.isDirectory()) {
          if(opened){assert.ok(opened.isDirectory());assertClientNamedDescriptor(named,opened);}
          const names=[],seen=new Set();let dir;
          try {
            dir=fs.opendirSync(file,{bufferSize:1});
            for(;;) {
              check();assert.ok(charged<=maxEntries,'CX_COMPLETE_TREE_ENTRY_BOUND');
              // One finite EOF/overflow probe is allowed at the exact cap.
              // A returned entry is charged before any name or path is retained.
              const entry=dir.readSync();check();if(!entry)break;
              check();assert.ok(entry.name!=='.'&&entry.name!=='..'&&!entry.name.includes(path.sep)&&!seen.has(entry.name),'CX_DUPLICATE_TREE_ENTRY');
              charge();seen.add(entry.name);names.push(entry.name);
            }
          } finally { if(dir)dir.closeSync(); }
          names.sort();row={path:relative,kind:'directory',metadata:meta(opened??named),names};
          for(const name of [...names].reverse()) {
            const child=path.join(file,name);assert.ok(!scheduled.has(child),'CX_DUPLICATE_TREE_ENTRY');scheduled.add(child);todo.push(child);
          }
        } else {
          assert.ok(opened?.isFile()&&named.isFile(),'CX_REGULAR_TREE_INPUT_REQUIRED');
          const value=readOpenedFile(file,fd,opened,maxBytes-bytes,check);bytes+=value.extent;
          assert.ok(bytes<=maxBytes,'CX_COMPLETE_TREE_BYTE_BOUND');
          row={path:relative,kind:'file',metadata:value.metadata,sha256:value.sha256};
        }
        assert.deepEqual(meta(fs.lstatSync(file,{bigint:true})),meta(named));
        if(opened)assert.deepEqual(meta(fs.fstatSync(fd,{bigint:true})),meta(opened));
        const parents=canonicalParents(path.dirname(file));
        states.set(file,{named:meta(named),parents,kind:row.kind,target:row.target});rows.push(row);
      } finally { if(fd!==undefined)fs.closeSync(fd); }
    }
    assert.ok(states.has(root),'CX_COMPLETE_TREE_ROOT_REQUIRED');
    rows.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
    return {rows,states};
  }
  const first=inventory(),logicalBytes=bytes,second=inventory();assert.deepEqual(second.rows,first.rows,'CX_COMPLETE_TREE_INVENTORY_CHANGED');
  for(const [file,state]of second.states) {
    check();assert.deepEqual(meta(fs.lstatSync(file,{bigint:true})),state.named,'CX_COMPLETE_TREE_FINAL_PATH_CHANGED');
    assert.deepEqual(canonicalParents(path.dirname(file)),state.parents,'CX_COMPLETE_TREE_FINAL_NAMESPACE_CHANGED');
    if(state.kind==='symlink') {
      const real=fs.realpathSync(file);assert.ok(real===root||real.startsWith(root+path.sep),'CX_EXTERNAL_TOOL_SYMLINK');
      assert.equal(fs.readlinkSync(file),state.target);
    }
  }
  check();return {schemaVersion:2,observations:2,root,entries:first.rows,bytes:logicalBytes,chargedBytes:bytes,chargedEntries:charged,complete:true};
}

export function clientHarnessFingerprint(root) {
  const names=['compose.mobile-local.yml','package.json','package-lock.json','apps/mobile/package.json','apps/mobile/package-lock.json'];
  for(const dir of ['apps/mobile/e2e','scripts/mobile'])for(const name of fs.readdirSync(path.join(root,dir)))
    if(/\.(mjs|py|json)$/.test(name))names.push(dir+'/'+name);
  const hash=createHash('sha256');for(const name of [...new Set(names)].sort()){
    const observed=captureClientFile(path.join(root,name),1048576);hash.update(name+'\0'+observed.sha256+'\0');
  }return hash.digest('hex');
}

export function clientListenerIdentity(value,pid,port) {
 assert.ok(typeof value==='string'&&Buffer.byteLength(value)<=65536);const rows=value.trim().split('\n');let processId=null,fd=null;const descriptors=[];
 for(const row of rows){if(/^p[1-9][0-9]{0,9}$/.test(row)){assert.equal(processId,null);processId=Number(row.slice(1));}
  else if(/^f[0-9]{1,6}$/.test(row)){assert.equal(fd,null);fd=Number(row.slice(1));}
  else if(row.startsWith('n')){assert.ok(fd!==null);assert.ok(['127.0.0.1:'+port,'[::1]:'+port].includes(row.slice(1)),'CX_LOOPBACK_APPIUM_LISTENER_REQUIRED');descriptors.push(fd);fd=null;}
  else assert.fail('CX_EXACT_LISTENER_FIELDS_REQUIRED');
 }
 assert.equal(processId,pid);assert.equal(fd,null);assert.ok(descriptors.length>=1&&descriptors.length<=2);assert.equal(new Set(descriptors).size,descriptors.length);return{pid,port,descriptors};
}

export function admitClientServer(q,{command=execFileSync,read=ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256}).value}={}) {
  const server=read(q.appiumServerEvidence),inventory=read(q.appiumInventoryEvidence);
  assert.equal(server.observed,true);assert.equal(server.owned,true);assert.equal(server.platform,q.platform);
  assert.ok(Number.isSafeInteger(server.pid)&&server.pid>1);assert.equal(server.inventoryEvidence.sha256,q.appiumInventoryEvidence.sha256);
  assert.equal(server.appiumUrl,q.appiumUrl);const url=new URL(server.appiumUrl);
  assert.equal(url.protocol,'http:');assert.ok(['127.0.0.1','localhost','[::1]'].includes(url.hostname));assert.ok(Number(url.port)>=1024);
  assert.equal(inventory.complete,true);assert.equal(inventory.platform,q.platform);
  assert.ok(inventory.tree?.schemaVersion===2&&inventory.tree.observations===2,'CX_FRESH_TWO_OBSERVATION_TREE_REQUIRED');
  assert.deepEqual(captureClientTree(inventory.root),inventory.tree,'CX_COMPLETE_APPIUM_INVENTORY_CHANGED');
  const observed=command('/bin/ps',['-p',String(server.pid),'-o','lstart=','-o','command='],{
    encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();
  assert.equal(sha(Buffer.from(observed)),server.utcStartAndCommandSha256,'CX_OWNED_SERVER_IDENTITY_CHANGED');
  assert.ok(observed.includes(inventory.appiumEntry),'CX_EXACT_APPIUM_ENTRY_REQUIRED');
  const owner=command('/bin/ps',['-p',String(server.pid),'-o','uid='],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();assert.match(owner,/^[0-9]{1,10}$/);assert.equal(Number(owner),process.getuid());assert.equal(server.uid,process.getuid());
  const listener=command('/usr/sbin/lsof',['-nP','-a','-p',String(server.pid),'-iTCP:'+url.port,'-sTCP:LISTEN','-Fpfn'],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}});clientListenerIdentity(listener,server.pid,Number(url.port));
  return {server,inventory};
}
