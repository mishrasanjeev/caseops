import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { readClientPublicInput, assertClientNamedDescriptor } from './client-extension-public-input.mjs';

const fields=['dev','ino','uid','gid','mode','nlink','size','mtimeNs','ctimeNs'];
const identityFields=['dev','ino','uid','gid','mode'];
const meta=s=>Object.fromEntries(fields.map(k=>[k,String(s[k])]));
const rawMeta=s=>Object.freeze(Object.fromEntries(fields.map(k=>{const value=s[k];assert.equal(typeof value,'bigint');return[k,value];})));
function assertMetadataEqual(actual,expected,code) {
  for(const key of fields)assert.equal(actual[key],expected[key],code);
}
const sha=b=>createHash('sha256').update(b).digest('hex');
const canonical=file=>(fs.realpathSync.native??fs.realpathSync)(file);
function canonicalParents(file) {
  assert.equal(canonical(file),file,'CX_CANONICAL_RUNTIME_NAMESPACE_REQUIRED');const result=[];
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
function admitOpenedRegular(opened, maxBytes, frame=opened) {
  assert.ok(opened.isFile() && frame.nlink === 1n && frame.size <= BigInt(maxBytes), 'CX_COMPLETE_TREE_BYTE_BOUND');
  if (typeof process.getuid === 'function') assert.equal(frame.uid, BigInt(process.getuid()));
}
function readOpenedFile(file, fd, opened, maxBytes, check = () => {}, namespace = canonicalParents, buffer = Buffer.alloc(65536), initial) {
  const openedFrame=initial?.openedFrame??rawMeta(opened);
  admitOpenedRegular(opened, maxBytes, openedFrame);
  const named = initial?.named ?? fs.lstatSync(file, { bigint: true }),namedFrame=initial?.namedFrame??rawMeta(named);
  assert.ok(named.isFile() && !named.isSymbolicLink());
  assertClientNamedDescriptor(namedFrame, openedFrame);
  const parents = namespace(file), hash = createHash('sha256');
  const extent=Number(openedFrame.size);let bytes = 0;
  while (bytes <= maxBytes) {
    check();
    const remaining=extent-bytes,width=Math.min(buffer.length,maxBytes+1-bytes);
    const n = fs.readSync(fd, buffer, 0, width, null);
    if (!n) break;
    bytes += n; assert.ok(bytes <= maxBytes, 'CX_COMPLETE_TREE_BYTE_BOUND'); hash.update(buffer.subarray(0,n));
    // A short read that included the growth sentinel already observed the end
    // of the admitted extent. Exact buffer boundaries and partial reads still
    // require another read; the independent final FD/named frames remain below.
    if(width>remaining && n===remaining)break;
  }
  assert.equal(BigInt(bytes), openedFrame.size);
  const finalParents=namespace(file);
  if(parents!==undefined)assert.deepEqual(finalParents,parents);
  assertMetadataEqual(fs.fstatSync(fd, {bigint:true}), openedFrame);
  const finalNamed = fs.lstatSync(file, {bigint:true});
  assertMetadataEqual(finalNamed, namedFrame); assertClientNamedDescriptor(finalNamed, openedFrame);
  return {path:file, sha256:hash.digest('hex'), extent:bytes, metadata:meta(openedFrame)};
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
function captureTree(root,{maxEntries=50000,maxBytes=536870912,timeoutMs=5000}={},project=value=>value) {
  assert.ok(Number.isSafeInteger(maxEntries) && maxEntries > 0 && maxEntries <= 50000);
  assert.ok(Number.isSafeInteger(maxBytes) && maxBytes > 0 && maxBytes <= 536870912);
  assert.ok(Number.isSafeInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 5000);
  const deadline = performance.now()+timeoutMs; let charged=0,bytes=0;
  const check=()=>assert.ok(performance.now()<deadline,'CX_COMPLETE_TREE_DEADLINE');
  const charge=()=>{check();assert.ok(charged<maxEntries,'CX_COMPLETE_TREE_ENTRY_BOUND');charged++;};
  assert.equal(path.resolve(root),root); assert.equal(canonical(root),root);check();
  const ancestors=canonicalParents(root),buffer=Buffer.alloc(65536);
  const externalFence=()=>{check();assert.deepEqual(canonicalParents(root),ancestors,'CX_COMPLETE_TREE_ROOT_NAMESPACE_CHANGED');};
  function inventory() {
    const rows=[],states=new Map(),scheduled=new Set(),todo=[];
    externalFence();
    // Every directory inside root has one complete descriptor/named frame in
    // this observation. Shared external ancestors are bound once per inventory
    // and again at the final fence; they are not restatted for every file.
    const namespace=file=>{
      check();assert.equal(canonical(file),file,'CX_CANONICAL_RUNTIME_NAMESPACE_REQUIRED');
      if(file!==root)for(let parent=path.dirname(file);;parent=path.dirname(parent)){
        check();const state=states.get(parent);assert.ok(state?.kind==='directory','CX_TREE_PARENT_NOT_ADMITTED');
        const value=fs.lstatSync(parent,{bigint:true});assert.ok(value.isDirectory()&&!value.isSymbolicLink());
        for(const key of identityFields)assert.equal(value[key],state.named[key],'CX_TREE_PARENT_IDENTITY_CHANGED');
        if(parent===root)break;
      }
      // Both live checks compare against the same immutable admitted baseline.
      // Native canonical resolution above also binds every external component;
      // external identity fences remain independent at each inventory boundary.
    };
    const schedule=file=>{assert.ok(!scheduled.has(file),'CX_DUPLICATE_TREE_ENTRY');charge();scheduled.add(file);todo.push(file);};
    schedule(root);
    while(todo.length) {
      check();const file=todo.pop(),relative=path.relative(root,file);let fd,opened,named,openedFrame,namedFrame;
      try {
        try {
          fd=fs.openSync(file,fs.constants.O_RDONLY|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0));
          opened=fs.fstatSync(fd,{bigint:true});openedFrame=rawMeta(opened);
          if(file===root)assert.ok(opened.isDirectory(),'CX_TREE_ROOT_DIRECTORY_REQUIRED');
          if(opened.isFile())admitOpenedRegular(opened,maxBytes,openedFrame);
          named=fs.lstatSync(file,{bigint:true});namedFrame=rawMeta(named);
        } catch(error) {
          if(fd!==undefined)throw error;
          named=fs.lstatSync(file,{bigint:true});namedFrame=rawMeta(named);
          const directoryFallback=process.platform==='win32'&&named.isDirectory()&&['EISDIR','EPERM'].includes(error.code);
          if(!named.isSymbolicLink()&&!directoryFallback)throw error;
        }
        if(file===root)assert.ok(named.isDirectory()&&!named.isSymbolicLink(),'CX_TREE_ROOT_DIRECTORY_REQUIRED');
        if(typeof process.getuid==='function')assert.equal(namedFrame.uid,BigInt(process.getuid()));
        let row;
        if(named.isSymbolicLink()) {
          const target=fs.readlinkSync(file),real=fs.realpathSync(file);
          assert.ok(real===root||real.startsWith(root+path.sep),'CX_EXTERNAL_TOOL_SYMLINK');
          row={path:relative,kind:'symlink',metadata:meta(namedFrame),target};
        } else if(named.isDirectory()) {
          if(opened){assert.ok(opened.isDirectory());assertClientNamedDescriptor(namedFrame,openedFrame);}
          namespace(file);
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
          names.sort();row={path:relative,kind:'directory',metadata:meta(openedFrame??namedFrame),names};
          for(const name of [...names].reverse()) {
            const child=path.join(file,name);assert.ok(!scheduled.has(child),'CX_DUPLICATE_TREE_ENTRY');scheduled.add(child);todo.push(child);
          }
        } else {
          assert.ok(opened?.isFile()&&named.isFile(),'CX_REGULAR_TREE_INPUT_REQUIRED');
          const value=readOpenedFile(file,fd,opened,maxBytes-bytes,check,namespace,buffer,{named,openedFrame,namedFrame});bytes+=value.extent;
          assert.ok(bytes<=maxBytes,'CX_COMPLETE_TREE_BYTE_BOUND');
          row={path:relative,kind:'file',metadata:value.metadata,sha256:value.sha256};
        }
        if(row.kind!=='file') {
          assertMetadataEqual(fs.lstatSync(file,{bigint:true}),namedFrame);
          if(opened)assertMetadataEqual(fs.fstatSync(fd,{bigint:true}),openedFrame);
        }
        states.set(file,{named:namedFrame,kind:row.kind,target:row.target});rows.push(row);
      } finally { if(fd!==undefined)fs.closeSync(fd); }
    }
    assert.ok(states.has(root),'CX_COMPLETE_TREE_ROOT_REQUIRED');
    externalFence();
    rows.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);
    return {rows,states};
  }
  const first=inventory(),logicalBytes=bytes,second=inventory();assert.deepEqual(second.rows,first.rows,'CX_COMPLETE_TREE_INVENTORY_CHANGED');
  for(const [file,state]of second.states) {
    check();assertMetadataEqual(fs.lstatSync(file,{bigint:true}),state.named,'CX_COMPLETE_TREE_FINAL_PATH_CHANGED');
    if(state.kind==='symlink') {
      const real=canonical(file);assert.ok(real===root||real.startsWith(root+path.sep),'CX_EXTERNAL_TOOL_SYMLINK');
      assert.equal(fs.readlinkSync(file),state.target);
    }else assert.equal(canonical(file),file,'CX_COMPLETE_TREE_FINAL_NAMESPACE_CHANGED');
  }
  // Leaf namespace checks can themselves be the final observation boundary.
  // Reconcile every unique directory once more after all leaves, so a late
  // inserted entry cannot hide behind a root visited earlier in the loop.
  // A parent is admitted before its children. Reconcile in reverse order so
  // every parent, including root, is checked after its last descendant fence.
  const finalDirectories=[];
  for(const item of second.states)if(item[1].kind==='directory')finalDirectories.push(item);
  for(let i=finalDirectories.length-1;i>=0;i--){const [file,state]=finalDirectories[i];
    check();assertMetadataEqual(fs.lstatSync(file,{bigint:true}),state.named,'CX_COMPLETE_TREE_FINAL_PATH_CHANGED');
    assert.equal(canonical(file),file,'CX_COMPLETE_TREE_FINAL_NAMESPACE_CHANGED');
  }
  externalFence();
  check();const tree={schemaVersion:2,observations:2,root,entries:first.rows,bytes:logicalBytes,chargedBytes:bytes,chargedEntries:charged,complete:true};
  const result=project(tree,check);check();return result;
}

export function captureClientTree(root,options) { return captureTree(root,options); }

/** The asynchronous path changes only payload I/O scheduling. Both inventories
 * remain complete and serial; all admission/final namespace checks are live.
 * Every job settles and attempts close once before returning. Other definitely
 * held leases close independently; an ambiguous close requires process cleanup. */
async function captureTreeAsync(root,{maxEntries=50000,maxBytes=536870912,timeoutMs=5000}={},project=value=>value) {
  assert.ok(Number.isSafeInteger(maxEntries)&&maxEntries>0&&maxEntries<=50000);
  assert.ok(Number.isSafeInteger(maxBytes)&&maxBytes>0&&maxBytes<=536870912);
  assert.ok(Number.isSafeInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=5000);
  const deadline=performance.now()+timeoutMs,buffers=Array.from({length:4},()=>Buffer.alloc(65536));
  const jobs=new Set(),waiters=new Set(),cleanupErrors=[];let charged=0,bytes=0,reserved=0,pendingOpens=0,failure,result;
  const wake=()=>{const waiting=[...waiters];waiters.clear();for(const resolve of waiting)resolve();};
  const fail=error=>{failure??=error;wake();};
  const check=()=>{if(failure)throw failure;assert.ok(performance.now()<deadline,'CX_COMPLETE_TREE_DEADLINE');};
  const progress=()=>new Promise(resolve=>waiters.add(resolve));
  const charge=()=>{check();assert.ok(charged<maxEntries,'CX_COMPLETE_TREE_ENTRY_BOUND');charged++;};
  const timer=setTimeout(()=>fail(new Error('CX_COMPLETE_TREE_DEADLINE')),Math.max(1,deadline-performance.now()));
  const close=fd=>{
    try{fs.closeSync(fd);}catch(error){
      cleanupErrors.push(error);fail(error);
      // The numeric descriptor may already identify a caller's new lease, even
      // for the same inode and full metadata. Only the isolated process owner
      // can close this uncertainty; no second close or ownership probe is safe.
    }
  };
  const drain=async()=>{while(jobs.size)await progress();};
  async function readChunk(fd,buffer) {
    let width;
    for(;;){
      check();const available=maxBytes+1-bytes-reserved;
      if(available>0){width=Math.min(buffer.length,available);reserved+=width;break;}
      assert.ok(reserved>0,'CX_COMPLETE_TREE_BYTE_BOUND');await progress();
    }
    return new Promise((resolve,reject)=>{
      let completed=false;
      const done=(error,n)=>{
        if(completed){fail(new Error('CX_CAPTURE_READ_CALLBACK_REPEATED'));return;}completed=true;
        reserved-=width;
        try{
          // Charge a reported partial count even when the same syscall fails.
          // An error with no count cannot certify a capture; its reservation
          // still bounds the attempted I/O and no further read is admitted.
          const knownCount=Number.isSafeInteger(n)&&n>=0&&n<=width;
          if(knownCount)bytes+=n;
          if(error)throw error;
          assert.ok(knownCount,'CX_CAPTURE_READ_COUNT_REQUIRED');
          assert.ok(bytes<=maxBytes,'CX_COMPLETE_TREE_BYTE_BOUND');check();resolve({n,width});
        }catch(error){fail(error);reject(error);}finally{wake();}
      };
      try{fs.read(fd,buffer,0,width,null,done);}catch(error){done(error,0);}
    });
  }
  const openAsync=file=>new Promise((resolve,reject)=>{
    check();assert.ok(jobs.size+pendingOpens<4,'CX_CAPTURE_FOUR_FILE_JOBS_REQUIRED');pendingOpens++;
    let completed=false;
    const unknown=error=>{cleanupErrors.push(error);fail(error);};
    const done=(error,fd)=>{
      if(completed){unknown(new Error('CX_CAPTURE_OPEN_CALLBACK_REPEATED'));return;}completed=true;pendingOpens--;
      if(error){
        if(fd!==undefined&&fd!==null&&fd!==-1){cleanupErrors.push(new Error('CX_CAPTURE_OPEN_ACK_UNCERTAIN'));fail(error);}
        // The caller still owns the reviewed symlink/Windows-directory
        // fallback classification for an ordinary no-descriptor error.
        reject(error);return;
      }
      if(!Number.isInteger(fd)||fd<0){const error=new Error('CX_CAPTURE_OPEN_ACK_UNCERTAIN');unknown(error);reject(error);return;}
      // Always transfer a successful lease into the caller's owned finally,
      // even when another job or the timer has already refused the capture.
      resolve(fd);
    };
    try{fs.open(file,fs.constants.O_RDONLY|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0),done);}
    catch(error){unknown(error);done(error);}
  });
  const canonicalAsync=file=>new Promise((resolve,reject)=>{
    let completed=false;
    const done=(error,value)=>{
      if(completed){fail(new Error('CX_CAPTURE_CANONICAL_CALLBACK_REPEATED'));return;}completed=true;
      try{if(error)throw error;check();assert.equal(typeof value,'string');resolve(value);}
      catch(error){fail(error);reject(error);}
    };
    try{check();(fs.realpath.native??fs.realpath)(file,done);}catch(error){done(error);}
  });
  const safeIdentity=named=>{
    const numbers={};
    for(const key of identityFields){const value=named[key],number=Number(value);if(!Number.isSafeInteger(number)||BigInt(number)!==value)return undefined;numbers[key]=number;}
    return Object.freeze(numbers);
  };
  async function readLeaf(file,fd,opened,openedFrame,named,namedFrame,namespace,buffer) {
    admitOpenedRegular(opened,maxBytes,openedFrame);
    assert.ok(named.isFile()&&!named.isSymbolicLink());assertClientNamedDescriptor(namedFrame,openedFrame);
    await namespace(file);
    // A canonical callback can yield after descriptor admission. Rebind BOTH
    // independent frames before allowing any payload byte through that gap.
    assertMetadataEqual(fs.fstatSync(fd,{bigint:true}),openedFrame);
    const admittedNamed=fs.lstatSync(file,{bigint:true});assertMetadataEqual(admittedNamed,namedFrame);assertClientNamedDescriptor(admittedNamed,openedFrame);
    const hash=createHash('sha256'),extent=Number(openedFrame.size);let count=0;
    for(;;){
      check();const remaining=extent-count,{n,width}=await readChunk(fd,buffer);
      if(!n)break;
      count+=n;hash.update(buffer.subarray(0,n));
      if(width>remaining&&n===remaining)break;
    }
    assert.equal(BigInt(count),openedFrame.size);await namespace(file);
    assertMetadataEqual(fs.fstatSync(fd,{bigint:true}),openedFrame);
    const finalNamed=fs.lstatSync(file,{bigint:true});assertMetadataEqual(finalNamed,namedFrame);assertClientNamedDescriptor(finalNamed,openedFrame);
    return {path:path.relative(root,file),kind:'file',metadata:meta(openedFrame),sha256:hash.digest('hex')};
  }
  try{
    assert.equal(path.resolve(root),root);assert.equal(canonical(root),root);check();
    const ancestors=canonicalParents(root);
    const externalFence=()=>{check();assert.deepEqual(canonicalParents(root),ancestors,'CX_COMPLETE_TREE_ROOT_NAMESPACE_CHANGED');};
    async function inventory() {
      const rows=[],states=new Map(),scheduled=new Set(),todo=[];externalFence();
      const liveParents=file=>{
        if(file!==root){
          const parent=path.dirname(file),admitted=states.get(parent);assert.ok(admitted?.kind==='directory','CX_TREE_PARENT_NOT_ADMITTED');
          let link=admitted.parentChain;assert.equal(link.path,parent,'CX_TREE_PARENT_NOT_ADMITTED');
          for(;link;link=link.parent){
            check();
            // Only admitted primitive paths/baselines are retained. Every call
            // still observes each live parent, in the same child-to-root order.
            const value=link.numeric?fs.lstatSync(link.path):fs.lstatSync(link.path,{bigint:true});assert.ok(value.isDirectory()&&!value.isSymbolicLink());
            for(const key of identityFields){
              const actual=value[key];
              if(link.numeric&&!Number.isSafeInteger(actual))assert.ok(false,'CX_TREE_PARENT_IDENTITY_UNSAFE');
              if(!Object.is(actual,link.expected[key]))assert.fail('CX_TREE_PARENT_IDENTITY_CHANGED');
            }
          }
        }
      };
      const namespace=file=>{check();assert.equal(canonical(file),file,'CX_CANONICAL_RUNTIME_NAMESPACE_REQUIRED');liveParents(file);};
      const fileNamespace=async file=>{check();assert.equal(await canonicalAsync(file),file,'CX_CANONICAL_RUNTIME_NAMESPACE_REQUIRED');liveParents(file);};
      const schedule=file=>{assert.ok(!scheduled.has(file),'CX_DUPLICATE_TREE_ENTRY');charge();scheduled.add(file);todo.push(file);};
      const launch=(file,fd,opened,openedFrame,named,namedFrame)=>{
        const buffer=buffers.pop();assert.ok(buffer&&jobs.size<4,'CX_CAPTURE_FOUR_FILE_JOBS_REQUIRED');const job={};jobs.add(job);
        job.done=(async()=>{
          try{const row=await readLeaf(file,fd,opened,openedFrame,named,namedFrame,fileNamespace,buffer);check();states.set(file,{named:namedFrame,kind:'file'});rows.push(row);}
          catch(error){fail(error);}
          finally{close(fd);buffers.push(buffer);jobs.delete(job);wake();}
        })();
      };
      schedule(root);
      try{
        while(todo.length){
          check();while(jobs.size>=4){await progress();check();}
          const file=todo.pop(),relative=path.relative(root,file);let fd,opened,named,openedFrame,namedFrame;
          try{
            try{
              fd=await openAsync(file);check();
              opened=fs.fstatSync(fd,{bigint:true});openedFrame=rawMeta(opened);
              if(file===root)assert.ok(opened.isDirectory(),'CX_TREE_ROOT_DIRECTORY_REQUIRED');
              if(opened.isFile())admitOpenedRegular(opened,maxBytes,openedFrame);
              named=fs.lstatSync(file,{bigint:true});namedFrame=rawMeta(named);
            }catch(error){
              if(fd!==undefined)throw error;
              named=fs.lstatSync(file,{bigint:true});namedFrame=rawMeta(named);
              const directoryFallback=process.platform==='win32'&&named.isDirectory()&&['EISDIR','EPERM'].includes(error.code);
              if(!named.isSymbolicLink()&&!directoryFallback)throw error;
            }
            if(file===root)assert.ok(named.isDirectory()&&!named.isSymbolicLink(),'CX_TREE_ROOT_DIRECTORY_REQUIRED');
            if(typeof process.getuid==='function')assert.equal(namedFrame.uid,BigInt(process.getuid()));
            let row;
            if(named.isSymbolicLink()){
              const target=fs.readlinkSync(file),real=fs.realpathSync(file);assert.ok(real===root||real.startsWith(root+path.sep),'CX_EXTERNAL_TOOL_SYMLINK');
              row={path:relative,kind:'symlink',metadata:meta(namedFrame),target};
            }else if(named.isDirectory()){
              // Together with this descriptor and the iterator, no more than
              // four owned descriptors are live, including pending file jobs.
              while(jobs.size>2){await progress();check();}
              if(opened){assert.ok(opened.isDirectory());assertClientNamedDescriptor(namedFrame,openedFrame);}namespace(file);
              const names=[],seen=new Set();let dir;
              try{
                dir=fs.opendirSync(file,{bufferSize:1});
                for(;;){
                  check();assert.ok(charged<=maxEntries,'CX_COMPLETE_TREE_ENTRY_BOUND');const entry=dir.readSync();check();if(!entry)break;
                  assert.ok(entry.name!=='.'&&entry.name!=='..'&&!entry.name.includes(path.sep)&&!seen.has(entry.name),'CX_DUPLICATE_TREE_ENTRY');
                  charge();seen.add(entry.name);names.push(entry.name);
                }
              }finally{if(dir)try{dir.closeSync();}catch(error){cleanupErrors.push(error);fail(error);}}
              names.sort();row={path:relative,kind:'directory',metadata:meta(openedFrame??namedFrame),names};
              for(const name of [...names].reverse()){const child=path.join(file,name);assert.ok(!scheduled.has(child),'CX_DUPLICATE_TREE_ENTRY');scheduled.add(child);todo.push(child);}
            }else{
              assert.ok(opened?.isFile()&&named.isFile(),'CX_REGULAR_TREE_INPUT_REQUIRED');launch(file,fd,opened,openedFrame,named,namedFrame);fd=undefined;continue;
            }
            assertMetadataEqual(fs.lstatSync(file,{bigint:true}),namedFrame);if(opened)assertMetadataEqual(fs.fstatSync(fd,{bigint:true}),openedFrame);
            const numericIdentity=row.kind==='directory'?safeIdentity(namedFrame):undefined;
            let parentChain;
            if(row.kind==='directory'){
              const parent=file===root?null:states.get(path.dirname(file));
              assert.ok(file===root||parent?.kind==='directory','CX_TREE_PARENT_NOT_ADMITTED');
              parentChain=Object.freeze({path:file,expected:numericIdentity??namedFrame,numeric:numericIdentity!==undefined,parent:parent?.parentChain??null});
            }
            states.set(file,{named:namedFrame,kind:row.kind,target:row.target,numericIdentity,parentChain});rows.push(row);
          }catch(error){fail(error);}finally{if(fd!==undefined)close(fd);}
          check();
        }
        await drain();check();assert.equal(pendingOpens,0);assert.ok(states.has(root),'CX_COMPLETE_TREE_ROOT_REQUIRED');externalFence();
        rows.sort((a,b)=>a.path<b.path?-1:a.path>b.path?1:0);return {rows,states};
      }catch(error){fail(error);await drain();throw failure;}
    }
    const first=await inventory(),logicalBytes=bytes,second=await inventory();assert.deepEqual(second.rows,first.rows,'CX_COMPLETE_TREE_INVENTORY_CHANGED');
    // File jobs are fully drained before this separate four-worker phase.
    // On any refusal every already-dispatched canonical callback settles before
    // returning; no Promise.race, detached callback, or borrowed descriptor.
    const remaining=second.states.entries();
    const finalWorker=async()=>{
      for(;;){
        try{
          check();const next=remaining.next();if(next.done)return;const [file,state]=next.value;
          assertMetadataEqual(fs.lstatSync(file,{bigint:true}),state.named,'CX_COMPLETE_TREE_FINAL_PATH_CHANGED');
          const real=await canonicalAsync(file);
          if(state.kind==='symlink'){assert.ok(real===root||real.startsWith(root+path.sep),'CX_EXTERNAL_TOOL_SYMLINK');assert.equal(fs.readlinkSync(file),state.target);}
          else assert.equal(real,file,'CX_COMPLETE_TREE_FINAL_NAMESPACE_CHANGED');
          // Retain the original independent named frame across this new yield.
          assertMetadataEqual(fs.lstatSync(file,{bigint:true}),state.named,'CX_COMPLETE_TREE_FINAL_PATH_CHANGED');
        }catch(error){fail(error);return;}
      }
    };
    await Promise.all(Array.from({length:4},()=>finalWorker()));check();
    const directories=[...second.states].filter(([,state])=>state.kind==='directory');
    for(let i=directories.length-1;i>=0;i--){const [file,state]=directories[i];check();assertMetadataEqual(fs.lstatSync(file,{bigint:true}),state.named,'CX_COMPLETE_TREE_FINAL_PATH_CHANGED');assert.equal(canonical(file),file,'CX_COMPLETE_TREE_FINAL_NAMESPACE_CHANGED');}
    externalFence();check();result=project({schemaVersion:2,observations:2,root,entries:first.rows,bytes:logicalBytes,chargedBytes:bytes,chargedEntries:charged,complete:true},check);check();
  }catch(error){fail(error);}finally{await drain();clearTimeout(timer);}
  if(failure){
    const errors=[failure,...cleanupErrors.filter(error=>error!==failure)];
    if(cleanupErrors.length){const error=new AggregateError(errors,failure.message,{cause:failure});error.captureCleanupUncertain=true;error.captureRequiresProcessExit=true;throw error;}
    throw failure;
  }
  check();return result;
}

export function captureClientTreeAsync(root,options) { return captureTreeAsync(root,options); }

// This audit-output role is distinct from the unchanged one-MiB public reader
// and projection writer. Full manifests are never native admission inputs.
export const CLIENT_TREE_AUDIT_MAX_BYTES=16777216;
const TREE_ENCODING='caseops-client-tree-v2-json-lf';
function exactKeys(value,keys) {
  assert.ok(value&&typeof value==='object'&&!Array.isArray(value),'CX_TREE_SHAPE_REQUIRED');
  const actual=Object.keys(value);assert.equal(actual.length,keys.length,'CX_TREE_SHAPE_REQUIRED');
  assert.deepEqual(actual.sort(),[...keys].sort(),'CX_TREE_SHAPE_REQUIRED');
}
function integer(value,max) { assert.ok(Number.isSafeInteger(value)&&value>=0&&value<=max,'CX_TREE_COUNTS_REQUIRED'); }
function text(value) { assert.ok(typeof value==='string'&&value.length<=1048576,'CX_TREE_TEXT_BOUND'); }
function captureCounts(value,count) {
  integer(count,25000);assert.ok(count>=1,'CX_TREE_ROOT_DIRECTORY_REQUIRED');
  integer(value.bytes,268435456);integer(value.chargedBytes,536870912);integer(value.chargedEntries,50000);
  assert.equal(value.chargedEntries,count*2,'CX_TREE_TWO_OBSERVATION_COUNTS_REQUIRED');
  assert.equal(value.chargedBytes,value.bytes*2,'CX_TREE_TWO_OBSERVATION_COUNTS_REQUIRED');
}

/** Fixed field order, exact full v2 fields and one LF. This codec by itself
 * makes no fresh-observation claim; native admission uses the capture below. */
function treeMaterial(tree,check) {
  check();
  exactKeys(tree,['schemaVersion','observations','root','entries','bytes','chargedBytes','chargedEntries','complete']);
  const schemaVersion=tree.schemaVersion,observations=tree.observations,complete=tree.complete,root=tree.root,entries=tree.entries,logicalBytes=tree.bytes,chargedBytes=tree.chargedBytes,chargedEntries=tree.chargedEntries;
  assert.ok(schemaVersion===2&&observations===2&&complete===true,'CX_FRESH_TWO_OBSERVATION_TREE_REQUIRED');
  text(root);assert.ok(path.isAbsolute(root)&&path.resolve(root)===root,'CX_NORMALIZED_RUNTIME_PATH_REQUIRED');assert.ok(Array.isArray(entries));const count=entries.length;
  captureCounts({bytes:logicalBytes,chargedBytes,chargedEntries},count);
  const chunks=[],numeric=/^-?(?:0|[1-9][0-9]{0,39})$/,metadataKeys=fields.map(key=>JSON.stringify(key)+':"'),sizeIndex=fields.indexOf('size');let extent=0,fileBytes=0,names=0,previous;
  const emit=token=>{check();const n=Buffer.byteLength(token);assert.ok(extent+n<=CLIENT_TREE_AUDIT_MAX_BYTES,'CX_TREE_MANIFEST_OUTPUT_BOUND');chunks.push(token);extent+=n;};
  const string=value=>{check();text(value);emit(JSON.stringify(value));};
  emit('{"schemaVersion":2,"observations":2,"root":');string(root);emit(',"entries":[');
  for(let i=0;i<count;i++) {
    check();const row=entries[i],kind=row?.kind;assert.ok(['directory','file','symlink'].includes(kind),'CX_TREE_ROW_KIND_REQUIRED');
    exactKeys(row,['path','kind','metadata',kind==='directory'?'names':kind==='file'?'sha256':'target']);
    const rowPath=row.path,metadata=row.metadata;text(rowPath);assert.ok(i===0?rowPath===''&&kind==='directory':rowPath!==''&&previous<rowPath,'CX_TREE_ORDER_REQUIRED');previous=rowPath;
    exactKeys(metadata,fields);
    // Retain each checked numeric primitive once. Only fixed ASCII keys and
    // validated decimal strings enter this bounded chunk; names still stream.
    const values=fields.map(key=>{check();const value=metadata[key];assert.ok(typeof value==='string'&&numeric.test(value),'CX_TREE_METADATA_REQUIRED');return value;});
    const metadataToken=',"metadata":{'+values.map((value,k)=>metadataKeys[k]+value+'"').join(',')+'}';assert.ok(Buffer.byteLength(metadataToken)<=512,'CX_TREE_METADATA_CHUNK_BOUND');
    if(i)emit(',');emit('{"path":');string(rowPath);emit(',"kind":');string(kind);emit(metadataToken);
    if(kind==='directory') {
      const rowNames=row.names;assert.ok(Array.isArray(rowNames),'CX_TREE_DIRECTORY_COUNTS_REQUIRED');const length=rowNames.length;assert.ok(Number.isSafeInteger(length)&&length>=0&&length<count,'CX_TREE_DIRECTORY_COUNTS_REQUIRED');names+=length;assert.ok(names<count,'CX_TREE_DIRECTORY_COUNTS_REQUIRED');emit(',"names":[');let previousName;
      for(let n=0;n<length;n++){if(n)emit(',');const name=rowNames[n];string(name);assert.ok(name!==''&&(n===0||previousName<name),'CX_TREE_ORDER_REQUIRED');previousName=name;}emit(']');
    } else if(kind==='file') {
      const size=Number(values[sizeIndex]),digest=row.sha256;integer(size,268435456);fileBytes+=size;assert.ok(fileBytes<=logicalBytes,'CX_TREE_FILE_BYTES_REQUIRED');assert.match(digest,/^[a-f0-9]{64}$/);emit(',"sha256":');string(digest);
    } else { const target=row.target;emit(',"target":');string(target); }
    emit('}');
  }
  assert.equal(names,count-1,'CX_TREE_DIRECTORY_COUNTS_REQUIRED');assert.equal(fileBytes,logicalBytes,'CX_TREE_FILE_BYTES_REQUIRED');
  emit('],"bytes":'+logicalBytes+',"chargedBytes":'+chargedBytes+',"chargedEntries":'+chargedEntries+',"complete":true}\n');
  check();const bytes=Buffer.from(chunks.join(''));check();assert.equal(bytes.length,extent);
  const commitment={schemaVersion:3,kind:'caseops-client-tree-commitment',captureSchemaVersion:2,observations:2,complete:true,root,entryCount:count,bytes:logicalBytes,chargedEntries,chargedBytes,manifest:{encoding:TREE_ENCODING,sha256:sha(bytes),extent}};
  check();return {bytes,commitment};
}

export function clientTreeManifest(tree,{timeoutMs=5000}={}) {
  assert.ok(Number.isSafeInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=5000);
  const end=performance.now()+timeoutMs;return treeMaterial(tree,()=>assert.ok(performance.now()<end,'CX_COMPLETE_TREE_DEADLINE'));
}

export function assertClientTreeCommitment(value,root) {
  assert.ok(value?.schemaVersion===3&&value.kind==='caseops-client-tree-commitment'&&value.captureSchemaVersion===2&&value.observations===2&&value.complete===true,'CX_FRESH_TWO_OBSERVATION_TREE_REQUIRED');
  exactKeys(value,['schemaVersion','kind','captureSchemaVersion','observations','complete','root','entryCount','bytes','chargedEntries','chargedBytes','manifest']);
  text(value.root);assert.ok(path.isAbsolute(value.root)&&path.resolve(value.root)===value.root,'CX_NORMALIZED_RUNTIME_PATH_REQUIRED');if(root!==undefined)assert.equal(value.root,root,'CX_TREE_ROOT_CHANGED');captureCounts(value,value.entryCount);
  exactKeys(value.manifest,['encoding','sha256','extent']);assert.equal(value.manifest.encoding,TREE_ENCODING);assert.match(value.manifest.sha256,/^[a-f0-9]{64}$/);integer(value.manifest.extent,CLIENT_TREE_AUDIT_MAX_BYTES);assert.ok(value.manifest.extent>0);
  return value;
}

function capturedRuntimeFile(tree,file,check) {
  check();assert.ok(typeof file==='string'&&path.isAbsolute(file)&&path.resolve(file)===file&&file.startsWith(tree.root+path.sep),'CX_CANONICAL_CAPTURED_RUNTIME_FILE_REQUIRED');
  assert.equal(canonical(file),file,'CX_CANONICAL_CAPTURED_RUNTIME_FILE_REQUIRED');
  const relative=path.relative(tree.root,file),row=tree.entries.find(value=>value.path===relative);
  assert.equal(row?.kind,'file','CX_CAPTURED_RUNTIME_REGULAR_FILE_REQUIRED');
  const named=fs.lstatSync(file,{bigint:true});assert.ok(named.isFile()&&!named.isSymbolicLink(),'CX_CAPTURED_RUNTIME_REGULAR_FILE_REQUIRED');
  assertClientNamedDescriptor(named,Object.fromEntries(fields.map(key=>[key,BigInt(row.metadata[key])])));check();
}
export function captureClientTreeCommitment(root,options,requiredFile) {
  return captureTree(root,options,(tree,check)=>{if(requiredFile!==undefined)capturedRuntimeFile(tree,requiredFile,check);return treeMaterial(tree,check).commitment;});
}
export function captureClientTreeCommitmentAsync(root,options,requiredFile) {
  return captureTreeAsync(root,options,(tree,check)=>{if(requiredFile!==undefined)capturedRuntimeFile(tree,requiredFile,check);return treeMaterial(tree,check).commitment;});
}

function writeTreeAudit(file,material,check) {
  check();
  assert.ok(Buffer.isBuffer(material.bytes)&&material.bytes.length>0&&material.bytes.length<=CLIENT_TREE_AUDIT_MAX_BYTES,'CX_TREE_MANIFEST_OUTPUT_BOUND');
  assertClientTreeCommitment(material.commitment);assert.equal(material.bytes.length,material.commitment.manifest.extent);assert.equal(sha(material.bytes),material.commitment.manifest.sha256);
  assert.ok(path.isAbsolute(file)&&path.resolve(file)===file);const parent=path.dirname(file);assert.equal(canonical(parent),parent);assert.ok(parent!==material.commitment.root&&!parent.startsWith(material.commitment.root+path.sep),'CX_AUDIT_OUTPUT_OUTSIDE_RUNTIME_REQUIRED');
  const parentFrame=()=>{assert.equal(canonical(parent),parent);const value=fs.lstatSync(parent,{bigint:true});assert.ok(value.isDirectory()&&!value.isSymbolicLink());return [[parent,...['dev','ino','uid','gid','mode'].map(k=>String(value[k]))],...canonicalParents(parent)];};
  const parents=parentFrame();let fd;
  try {
    check();fd=fs.openSync(file,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|(fs.constants.O_NOFOLLOW??0)|(fs.constants.O_NONBLOCK??0),0o600);
    const opened=fs.fstatSync(fd,{bigint:true}),named=fs.lstatSync(file,{bigint:true});
    assert.ok(opened.isFile()&&opened.nlink===1n&&named.isFile()&&!named.isSymbolicLink());assertClientNamedDescriptor(named,opened);
    assert.deepEqual(parentFrame(),parents);check();
    if(process.getuid){assert.equal(opened.uid,BigInt(process.getuid()));assert.equal(opened.mode&0o777n,0o600n);}
    let offset=0;while(offset<material.bytes.length){check();const width=Math.min(65536,material.bytes.length-offset),n=fs.writeSync(fd,material.bytes,offset,width);assert.ok(Number.isSafeInteger(n)&&n>0&&n<=width);offset+=n;}
    check();fs.fsyncSync(fd);check();const after=fs.fstatSync(fd,{bigint:true}),final=fs.lstatSync(file,{bigint:true});
    assert.equal(after.size,BigInt(material.bytes.length));for(const key of ['dev','ino','uid','gid','mode','nlink'])assert.equal(after[key],opened[key]);
    assert.ok(final.isFile()&&!final.isSymbolicLink());assertClientNamedDescriptor(final,after);assert.deepEqual(meta(fs.fstatSync(fd,{bigint:true})),meta(after));assert.deepEqual(meta(fs.lstatSync(file,{bigint:true})),meta(final));assert.deepEqual(parentFrame(),parents);assert.equal(canonical(file),file);check();
    return {path:file,sha256:material.commitment.manifest.sha256,extent:offset,metadata:meta(after)};
  } finally { if(fd!==undefined)fs.closeSync(fd); }
}

export function writeClientTreeAuditManifest(file,material,{timeoutMs=5000}={}) {
  assert.ok(Number.isSafeInteger(timeoutMs)&&timeoutMs>0&&timeoutMs<=5000);const end=performance.now()+timeoutMs;
  return writeTreeAudit(file,material,()=>assert.ok(performance.now()<end,'CX_COMPLETE_TREE_DEADLINE'));
}

export function captureClientTreeInventory(root,manifestFile,options,requiredFile) {
  return captureTree(root,options,(tree,check)=>{if(requiredFile!==undefined)capturedRuntimeFile(tree,requiredFile,check);const material=treeMaterial(tree,check);const auditManifest=writeTreeAudit(manifestFile,material,check);return {root,tree:material.commitment,auditManifest};});
}
export function captureClientTreeInventoryAsync(root,manifestFile,options,requiredFile) {
  return captureTreeAsync(root,options,(tree,check)=>{if(requiredFile!==undefined)capturedRuntimeFile(tree,requiredFile,check);const material=treeMaterial(tree,check);const auditManifest=writeTreeAudit(manifestFile,material,check);return {root,tree:material.commitment,auditManifest};});
}

export function assertClientRuntimeInventory(value,purpose,platform) {
  assert.ok(['webdriver','appium'].includes(purpose)&&['ios','android'].includes(platform));
  exactKeys(value,['schemaVersion','kind','complete','platform','root','tree','auditManifest',...(purpose==='appium'?['appiumEntry']:[])]);
  assert.equal(value.schemaVersion,2);assert.equal(value.kind,'native-client-'+purpose+'-inventory');assert.equal(value.complete,true);assert.equal(value.platform,platform);assertClientTreeCommitment(value.tree,value.root);
  exactKeys(value.auditManifest,['path','sha256','extent','metadata']);text(value.auditManifest.path);assert.ok(path.isAbsolute(value.auditManifest.path)&&path.resolve(value.auditManifest.path)===value.auditManifest.path,'CX_NORMALIZED_RUNTIME_PATH_REQUIRED');assert.equal(value.auditManifest.sha256,value.tree.manifest.sha256);assert.equal(value.auditManifest.extent,value.tree.manifest.extent);exactKeys(value.auditManifest.metadata,fields);
  for(const key of fields)assert.ok(typeof value.auditManifest.metadata[key]==='string'&&/^-?(?:0|[1-9][0-9]{0,39})$/.test(value.auditManifest.metadata[key]),'CX_TREE_METADATA_REQUIRED');
  assert.equal(value.auditManifest.metadata.size,String(value.auditManifest.extent));assert.equal(value.auditManifest.metadata.nlink,'1');
  assert.ok(value.auditManifest.path!==value.root&&!value.auditManifest.path.startsWith(value.root+path.sep),'CX_AUDIT_OUTPUT_OUTSIDE_RUNTIME_REQUIRED');
  if(purpose==='appium'){text(value.appiumEntry);assert.ok(path.isAbsolute(value.appiumEntry)&&path.resolve(value.appiumEntry)===value.appiumEntry&&value.appiumEntry.startsWith(value.root+path.sep),'CX_CANONICAL_CAPTURED_RUNTIME_FILE_REQUIRED');}
  return value;
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
  assertClientTreeCommitment(inventory.tree,inventory.root);assertClientRuntimeInventory(inventory,'appium',q.platform);
  assert.deepEqual(captureClientTreeCommitment(inventory.root,undefined,inventory.appiumEntry),inventory.tree,'CX_COMPLETE_APPIUM_INVENTORY_CHANGED');
  const observed=command('/bin/ps',['-p',String(server.pid),'-o','lstart=','-o','command='],{
    encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();
  assert.equal(sha(Buffer.from(observed)),server.utcStartAndCommandSha256,'CX_OWNED_SERVER_IDENTITY_CHANGED');
  assert.ok(observed.includes(inventory.appiumEntry),'CX_EXACT_APPIUM_ENTRY_REQUIRED');
  const owner=command('/bin/ps',['-p',String(server.pid),'-o','uid='],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();assert.match(owner,/^[0-9]{1,10}$/);assert.equal(Number(owner),process.getuid());assert.equal(server.uid,process.getuid());
  const listener=command('/usr/sbin/lsof',['-nP','-a','-p',String(server.pid),'-iTCP:'+url.port,'-sTCP:LISTEN','-Fpfn'],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}});clientListenerIdentity(listener,server.pid,Number(url.port));
  return {server,inventory};
}

export async function admitClientServerAsync(q,{command=execFileSync,read=ref=>readClientPublicInput(ref.path,{expectedSha256:ref.sha256}).value}={}) {
  const server=read(q.appiumServerEvidence),inventory=read(q.appiumInventoryEvidence);
  assert.equal(server.observed,true);assert.equal(server.owned,true);assert.equal(server.platform,q.platform);
  assert.ok(Number.isSafeInteger(server.pid)&&server.pid>1);assert.equal(server.inventoryEvidence.sha256,q.appiumInventoryEvidence.sha256);
  assert.equal(server.appiumUrl,q.appiumUrl);const url=new URL(server.appiumUrl);
  assert.equal(url.protocol,'http:');assert.ok(['127.0.0.1','localhost','[::1]'].includes(url.hostname));assert.ok(Number(url.port)>=1024);
  assert.equal(inventory.complete,true);assert.equal(inventory.platform,q.platform);
  assertClientTreeCommitment(inventory.tree,inventory.root);assertClientRuntimeInventory(inventory,'appium',q.platform);
  assert.deepEqual(await captureClientTreeCommitmentAsync(inventory.root,undefined,inventory.appiumEntry),inventory.tree,'CX_COMPLETE_APPIUM_INVENTORY_CHANGED');
  const observed=command('/bin/ps',['-p',String(server.pid),'-o','lstart=','-o','command='],{
    encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();
  assert.equal(sha(Buffer.from(observed)),server.utcStartAndCommandSha256,'CX_OWNED_SERVER_IDENTITY_CHANGED');
  assert.ok(observed.includes(inventory.appiumEntry),'CX_EXACT_APPIUM_ENTRY_REQUIRED');
  const owner=command('/bin/ps',['-p',String(server.pid),'-o','uid='],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}}).trim();assert.match(owner,/^[0-9]{1,10}$/);assert.equal(Number(owner),process.getuid());assert.equal(server.uid,process.getuid());
  const listener=command('/usr/sbin/lsof',['-nP','-a','-p',String(server.pid),'-iTCP:'+url.port,'-sTCP:LISTEN','-Fpfn'],{encoding:'utf8',timeout:5000,maxBuffer:65536,env:{PATH:'/usr/bin:/bin',LC_ALL:'C',TZ:'UTC'}});clientListenerIdentity(listener,server.pid,Number(url.port));
  return {server,inventory};
}
