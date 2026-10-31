"""QA-only AGP merged-manifest transform. No ambient Python or production hook."""
from pathlib import Path
import argparse,hashlib,json,os,re,stat,sys,time,xml.etree.ElementTree as ET
A='http://schemas.android.com/apk/res/android';APP='ai.caseops.mobile.dev.localacceptance';PKG='ai.caseops.mobile.qa';PROCESS=APP+':privacyobserver'
FIELDS=('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
def need(value,code):
 if not value:raise RuntimeError(code)
def same(a,b):
 return all(getattr(a,k)==getattr(b,k)for k in FIELDS)
def named_matches_fd(named,opened,platform=os.name):
 return all(getattr(named,k)==getattr(opened,k)for k in FIELDS if not(k=='st_dev'and platform=='nt'and named.st_dev==0))
def owner():return os.getuid()if hasattr(os,'getuid')else Path.home().stat().st_uid
class Budget:
 def __init__(self):self.end=globals().get('_CASEOPS_OBSERVER_STARTED_MONOTONIC',time.monotonic())+15;self.bytes=0;self.entries=0
 def charge(self,n=0):
  self.entries+=1;self.bytes+=n;need(self.entries<=1024 and self.bytes<=67108864 and time.monotonic()<self.end,'QA_MANIFEST_BOUNDS')
def namespace(p,b):
 rows=[]
 for parent in p.parents:
  s=parent.lstat();b.charge();need(stat.S_ISDIR(s.st_mode)and not stat.S_ISLNK(s.st_mode),'QA_MANIFEST_NAMESPACE');rows.append((str(parent),s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid))
 return rows
def held(path,b,limit,capture=False):
 p=Path(path);ns=namespace(p,b);named=p.lstat();b.charge();need(stat.S_ISREG(named.st_mode)and not stat.S_ISLNK(named.st_mode)and named.st_nlink==1 and named.st_uid==owner()and named.st_size<=limit,'QA_MANIFEST_OWNED_FILE')
 fd=os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
 try:
  first=os.fstat(fd);b.charge();need(named_matches_fd(named,first),'QA_MANIFEST_OPEN_CHANGED');data=bytearray()
  while len(data)<=first.st_size:
   b.charge();part=os.read(fd,min(65536,first.st_size+1-len(data)));b.charge(len(part))
   if not part:break
   data.extend(part)
  final_fd=os.fstat(fd);b.charge();final_named=p.lstat();b.charge();need(len(data)==first.st_size and same(first,final_fd)and same(named,final_named)and named_matches_fd(final_named,final_fd)and namespace(p,b)==ns,'QA_MANIFEST_READ_CHANGED');return (bytes(data),[getattr(first,k)for k in FIELDS])if capture else bytes(data)
 finally:os.close(fd)
def output_namespace(path,root,b):
 p=Path(path);root=Path(root);need(p.is_absolute()and p==Path(os.path.normpath(p))and p.is_relative_to(root)and p!=root,'QA_MANIFEST_OUTPUT_SCOPE')
 # AGP declares these exact outputs. Its output-parent preparation precedes the
 # task action. This helper never creates directories, on any platform.
 rows=namespace(p,b);ancestor=p.parent
 while True:
  state=ancestor.lstat();b.charge();need(stat.S_ISDIR(state.st_mode)and not stat.S_ISLNK(state.st_mode)and state.st_uid==owner(),'QA_MANIFEST_OUTPUT_PARENT_OWNER')
  if ancestor==root:break
  need(ancestor.is_relative_to(root),'QA_MANIFEST_OUTPUT_SCOPE');ancestor=ancestor.parent
 return rows

def write_exact(path,data,b,root):
 p=Path(path);ns=output_namespace(p,root,b)
 if os.path.lexists(p):need(held(p,b,len(data))==data,'QA_MANIFEST_STALE_OWNED_OUTPUT');return
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
 try:
  before=os.fstat(fd);b.charge();initial_named=p.lstat();b.charge();need(stat.S_ISREG(before.st_mode)and before.st_uid==owner()and before.st_nlink==1 and named_matches_fd(initial_named,before),'QA_MANIFEST_OUTPUT_OWNER');pos=0
  while pos<len(data):b.charge();n=os.write(fd,data[pos:]);need(n>0,'QA_MANIFEST_WRITE');pos+=n
  os.fsync(fd);last=os.fstat(fd);b.charge();final_named=p.lstat();b.charge();confirmed=os.fstat(fd);b.charge()
  need(last.st_size==len(data)and all(getattr(before,k)==getattr(last,k)for k in('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink'))and all(getattr(initial_named,k)==getattr(final_named,k)for k in('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink'))and same(last,confirmed)and named_matches_fd(final_named,last)and output_namespace(p,root,b)==ns,'QA_MANIFEST_OUTPUT_CHANGED')
 finally:os.close(fd)

def attr(e,key):return e.get('{'+A+'}'+key)
def cname(value,package):
 need(isinstance(value,str)and bool(re.fullmatch(r'[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*|\.[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*',value)),'QA_MANIFEST_CLASS')
 return package+value if value.startswith('.')else value if'.'in value else package+'.'+value
def factory(base,source,processes):
 methods=[('android.app.Activity','instantiateActivity','ClassLoader c, String n, android.content.Intent i','c,n,i'),('android.app.Service','instantiateService','ClassLoader c, String n, android.content.Intent i','c,n,i'),('android.content.BroadcastReceiver','instantiateReceiver','ClassLoader c, String n, android.content.Intent i','c,n,i'),('android.content.ContentProvider','instantiateProvider','ClassLoader c, String n','c,n')]
 text=f'''package {PKG};
public final class QaObserverFactory extends android.app.AppComponentFactory {{
 private android.app.AppComponentFactory delegated;
 private boolean observer() {{ String p=android.app.Application.getProcessName(); if(!java.util.Arrays.asList({",".join(json.dumps(p)for p in processes)}).contains(p)) throw new SecurityException("QA_OBSERVER_UNKNOWN_PROCESS"); return "{PROCESS}".equals(p); }}
 private android.app.AppComponentFactory base() {{
  if(observer()) throw new SecurityException("QA_OBSERVER_BASE_CONSTRUCTION_REFUSED");
  if(delegated==null) delegated=new {base}();
  return delegated;
 }}
 @Override public ClassLoader instantiateClassLoader(ClassLoader c,android.content.pm.ApplicationInfo info) {{ return observer()?c:base().instantiateClassLoader(c,info); }}
 @Override public android.app.Application instantiateApplication(ClassLoader c,String n)throws InstantiationException,IllegalAccessException,ClassNotFoundException {{
  if(observer()) return new android.app.Application();
  return base().instantiateApplication(c,n);
 }}
'''
 for typ,name,args,call in methods:
  branch='if(!"'+PKG+'.QaPrivacyService".equals(n)) throw new SecurityException("QA_OBSERVER_COMPONENT_REFUSED"); return new QaPrivacyService();'if name=='instantiateService'else'throw new SecurityException("QA_OBSERVER_COMPONENT_REFUSED");'
  text+=f' @Override public {typ} {name}({args})throws InstantiationException,IllegalAccessException,ClassNotFoundException {{ if(observer()){{ {branch} }} return base().{name}({call}); }}\n'
 return(text+'}\n').encode()
def transform(raw,target,source):
 need(target==APP and re.fullmatch('[a-f0-9]{40}',source),'QA_MANIFEST_QA_ONLY');need(len(raw)<=1048576 and not re.search(br'<!\s*(DOCTYPE|ENTITY)',raw,re.I),'QA_MANIFEST_XML_DTD_REFUSED')
 root=ET.fromstring(raw);need(root.tag=='manifest'and root.get('package')==APP,'QA_MANIFEST_TARGET_PACKAGE');apps=root.findall('application');need(len(apps)==1,'QA_MANIFEST_ONE_APPLICATION');app=apps[0]
 need(attr(app,'debuggable')in(None,'false')and attr(app,'allowBackup')=='false','QA_MANIFEST_NONDEBUGGABLE_NO_BACKUP')
 main=attr(app,'process')or APP;need(main==APP,'QA_MANIFEST_MAIN_PROCESS')
 original=cname(attr(app,'name'),root.get('package'));need(original=='ai.caseops.mobile.dev.MainApplication','QA_MANIFEST_REVIEWED_APPLICATION')
 rawbase=attr(app,'appComponentFactory');base=cname(rawbase,APP)if rawbase is not None else'android.app.AppComponentFactory'
 need(not base.startswith(PKG+'.'),'QA_MANIFEST_ALREADY_PATCHED')
 components=[];initializers=[]
 for child in app:
  if child.tag in('activity','activity-alias','service','receiver','provider'):
   name=cname(attr(child,'name'),APP);process=attr(child,'process')or main;process=APP+process if process.startswith(':')else process
   need(process!=PROCESS and not name.startswith(PKG+'.'),'QA_MANIFEST_OBSERVER_PROCESS_COLLISION')
   need(child.tag!='provider'or attr(child,'multiprocess')not in('true',),'QA_MANIFEST_MULTIPROCESS_PROVIDER_UNREVIEWED')
   components.append({'kind':child.tag,'name':name,'process':process})
  for meta in child.iter('meta-data'):
   initializers.append({'parent':child.tag,'parentName':attr(child,'name'),'name':attr(meta,'name'),'valueSha256':hashlib.sha256((attr(meta,'value')or'').encode()).hexdigest(),'resource':attr(meta,'resource')})
 permission=APP+'.permission.QA_OBSERVE_PRIVATE';need(not any(attr(e,'name')==permission for e in root.findall('permission')),'QA_MANIFEST_PERMISSION_COLLISION')
 ET.SubElement(root,'permission',{'{'+A+'}name':permission,'{'+A+'}protectionLevel':'signature'})
 need(not any(attr(e,'name')=='caseops.qa.observer.sourceSha' for e in app.findall('meta-data')),'QA_MANIFEST_SOURCE_METADATA_COLLISION')
 ET.SubElement(app,'meta-data',{'{'+A+'}name':'caseops.qa.observer.sourceSha','{'+A+'}value':source})
 app.set('{'+A+'}appComponentFactory',PKG+'.QaObserverFactory');app.set('{'+A+'}name',PKG+'.QaMainApplication')
 ET.SubElement(app,'service',{'{'+A+'}name':PKG+'.QaPrivacyService','{'+A+'}process':':privacyobserver','{'+A+'}exported':'true','{'+A+'}permission':permission,'{'+A+'}isolatedProcess':'false','{'+A+'}stopWithTask':'false'})
 ET.register_namespace('android',A);manifest=ET.tostring(root,encoding='utf-8',xml_declaration=True)
 processes=sorted(set([main,PROCESS]+[row['process']for row in components]));wrapper=f'''package {PKG};
public final class QaMainApplication extends {original} {{
 @Override protected void attachBaseContext(android.content.Context base) {{
  super.attachBaseContext(base);
  String p=android.app.Application.getProcessName();
  if(!java.util.Arrays.asList({",".join(json.dumps(p)for p in processes if p!=PROCESS)}).contains(p)) throw new SecurityException("QA_MAIN_PROCESS_ROSTER");
  if("{APP}".equals(p) && !QaLifecycleWitness.install(this)) throw new SecurityException("QA_MAIN_OBSERVER_REGISTRATION_REQUIRED");
 }}
}}
'''.encode()
 audit={'schemaVersion':1,'kind':'actual-merged-qa-observer-transform','sourceSha':source,'target':target,'rawBaseFactory':rawbase,'rawBaseFactoryPresent':rawbase is not None,'effectiveRecordedBaseFactory':base,'originalApplication':original,'originalComponents':components,'allowedProcessRoster':processes,'originalInitializerRoster':initializers,'inputSha256':hashlib.sha256(raw).hexdigest(),'outputSha256':hashlib.sha256(manifest).hexdigest(),'mainProcess':main,'observerProcess':PROCESS,'observerApplication':'android.app.Application','productionTransform':False}
 return manifest,{'QaObserverFactory.java':factory(base,source,processes),'QaMainApplication.java':wrapper},audit

def admit_owner(q,b):
 envelope=os.environ.get('CASEOPS_ANDROID_OBSERVER_ADMISSION')
 if envelope is None:return None
 need(os.name=='posix'and sys.platform in('darwin','linux'),'QA_OBSERVER_OWNER_CHANNEL_PLATFORM')
 import fcntl,signal
 end=min(b.end,time.monotonic()+1);need(len(envelope.encode())<=4096,'QA_OBSERVER_OWNER_ENVELOPE_BOUND');ref=json.loads(envelope)
 need(type(ref)is dict and set(ref)=={'path','sha256','sizeBytes'}and type(ref['path'])is str and type(ref['sizeBytes'])is int and 0<ref['sizeBytes']<=16384 and re.fullmatch('[a-f0-9]{64}',ref['sha256'])is not None,'QA_OBSERVER_OWNER_ENVELOPE')
 request=Path(ref['path']);need(request.is_absolute()and request==Path(os.path.normpath(request))and request.name=='request.json','QA_OBSERVER_OWNER_REQUEST_PATH');raw,request_metadata=held(request,b,16384,capture=True);need(len(raw)==ref['sizeBytes']and hashlib.sha256(raw).hexdigest()==ref['sha256'],'QA_OBSERVER_OWNER_REQUEST_PIN');v=json.loads(raw);root=request.parent
 keys={'schemaVersion','kind','sourceSha','androidRoot','helper','python','nonce','run','directoryIdentity','lock'}
 need(type(v)is dict and set(v)==keys and v['schemaVersion']==1 and v['kind']=='caseops-qa-manifest-owner-request-v1'and v['sourceSha']==q.source and v['androidRoot']==q.android_root and root==Path(v['run'])/'role/observer-admission'and re.fullmatch('[a-f0-9]{32}',v['nonce'])is not None,'QA_OBSERVER_OWNER_REQUEST_BINDING')
 need(v['helper']['path']==str(Path(sys.argv[0]))and v['helper']['sha256']==globals().get('_CASEOPS_OBSERVER_HELPER_SHA256')and v['python']['path']==str(Path(sys.executable).resolve())and v['python']['sha256']==q.python_sha256,'QA_OBSERVER_OWNER_SOURCE_RUNTIME')
 def identity(s):return [s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid]
 before=root.lstat();need(stat.S_ISDIR(before.st_mode)and not stat.S_ISLNK(before.st_mode)and before.st_uid==owner()and stat.S_IMODE(before.st_mode)==0o700 and identity(before)==v['directoryIdentity'],'QA_OBSERVER_OWNER_DIRECTORY');ns=namespace(root,b);rootfd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);lockfd=None
 def check():b.charge();need(time.monotonic()<end and identity(os.fstat(rootfd))==identity(root.lstat())==v['directoryIdentity'],'QA_OBSERVER_OWNER_DEADLINE_OR_DIRECTORY')
 def names(expected):
  check();items=[]
  with os.scandir(rootfd)as iterator:
   for e in iterator:b.charge();need(e.name not in items and len(items)<5,'QA_OBSERVER_OWNER_DIRECTORY_MEMBERS');items.append(e.name)
  need(sorted(items)==sorted(expected),'QA_OBSERVER_OWNER_DIRECTORY_MEMBERS');check()
 def opened(name):
  check();n=os.stat(name,dir_fd=rootfd,follow_symlinks=False);b.charge();need(stat.S_ISREG(n.st_mode)and n.st_uid==owner()and n.st_nlink==1 and stat.S_IMODE(n.st_mode)==0o600,'QA_OBSERVER_OWNER_REGULAR');fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=rootfd)
  try:
   s=os.fstat(fd);b.charge();need(same(n,s)and s.st_size<=4096,'QA_OBSERVER_OWNER_OPEN');data=os.read(fd,s.st_size+1);b.charge(len(data));need(len(data)==s.st_size and same(s,os.fstat(fd))and same(n,os.stat(name,dir_fd=rootfd,follow_symlinks=False)),'QA_OBSERVER_OWNER_FD_CHANGED');check();return fd,data,s,n
  except BaseException:os.close(fd);raise
 def write(name,data):
  check();fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=rootfd)
  try:
   s=os.fstat(fd);b.charge();need(stat.S_ISREG(s.st_mode)and s.st_uid==owner()and s.st_nlink==1,'QA_OBSERVER_OWNER_OUTPUT');n=0
   while n<len(data):width=os.write(fd,data[n:]);b.charge(width);need(width>0,'QA_OBSERVER_OWNER_OUTPUT_PROGRESS');n+=width
   os.fsync(fd);last=os.fstat(fd);named=os.stat(name,dir_fd=rootfd,follow_symlinks=False);b.charge();need(last.st_size==len(data)and same(last,named)and all(getattr(s,k)==getattr(last,k)for k in('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink')),'QA_OBSERVER_OWNER_OUTPUT_CHANGED')
  finally:os.close(fd)
  check();return [getattr(last,k)for k in FIELDS]
 try:
  need(identity(os.fstat(rootfd))==v['directoryIdentity'],'QA_OBSERVER_OWNER_ROOT_FD');names(['lock','request.json']);lock=v['lock'];need(set(lock)=={'path','sha256','sizeBytes'}and lock['path']==str(root/'lock'),'QA_OBSERVER_OWNER_LOCK_SCOPE');lockfd,lockraw,lockfirst,locknamed=opened('lock');need(len(lockraw)==lock['sizeBytes']and hashlib.sha256(lockraw).hexdigest()==lock['sha256'],'QA_OBSERVER_OWNER_LOCK_PIN')
  ready={'schemaVersion':1,'kind':'caseops-qa-manifest-owner-ready-v1','nonce':v['nonce'],'requestSha256':ref['sha256'],'pid':os.getpid(),'ppid':os.getppid(),'sourceSha':q.source,'deadlineMonotonic':end};ready_raw=(json.dumps(ready,separators=(',',':'))+'\n').encode();ready_metadata=write('ready.json',ready_raw);seal={'schemaVersion':1,'kind':'caseops-qa-manifest-owner-ready-seal-v1','readySha256':hashlib.sha256(ready_raw).hexdigest(),'readyMetadata':ready_metadata};seal_metadata=write('ready-complete',(json.dumps(seal,separators=(',',':'))+'\n').encode())
  old=signal.getsignal(signal.SIGALRM);timer=signal.getitimer(signal.ITIMER_REAL);need(timer==(0.0,0.0),'QA_OBSERVER_OWNER_EXISTING_TIMER')
  def expired(*unused):raise RuntimeError('QA_OBSERVER_OWNER_ACK_DEADLINE')
  try:
   signal.signal(signal.SIGALRM,expired);check();signal.setitimer(signal.ITIMER_REAL,max(.000001,end-time.monotonic()));fcntl.flock(lockfd,fcntl.LOCK_SH)
  finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)
  check();need(same(lockfirst,os.fstat(lockfd))and same(locknamed,os.stat('lock',dir_fd=rootfd,follow_symlinks=False)),'QA_OBSERVER_OWNER_LOCK_CHANGED');ackfd,ackraw,_,_=opened('ack.json')
  try:ack=json.loads(ackraw)
  finally:os.close(ackfd)
  observed=ack.get('observedIdentity',{});expected=dict(ready,kind='caseops-qa-manifest-owner-ack-v1',requestMetadata=request_metadata,readyMetadata=ready_metadata,sealMetadata=seal_metadata,observedIdentity=observed);need(ack==expected and set(observed)=={'pid','ppid','pgid','uid','createdUtc','executable','argvSha256'}and observed['pid']==os.getpid()and observed['ppid']==os.getppid()and observed['pgid']==os.getpgid(0)and observed['uid']==owner()and observed['executable']==str(Path(sys.executable).resolve())and observed['argvSha256']==hashlib.sha256(json.dumps(sys.orig_argv,separators=(',',':')).encode()).hexdigest()and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z',observed['createdUtc'])is not None and [getattr(request.lstat(),k)for k in FIELDS]==request_metadata,'QA_OBSERVER_OWNER_ACK_BINDING');names(['lock','request.json','ready.json','ready-complete','ack.json']);need(namespace(root,b)==ns,'QA_OBSERVER_OWNER_NAMESPACE_CHANGED');return {'requestSha256':ref['sha256'],'ackSha256':hashlib.sha256(ackraw).hexdigest(),'nonce':v['nonce'],'transformPid':os.getpid(),'parentPid':os.getppid(),'ackWithinOriginalOneSecond':True}
 finally:
  if lockfd is not None:os.close(lockfd)
  os.close(rootfd)

def main(argv):
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output-root',required=True);p.add_argument('--manifest-output',required=True);p.add_argument('--android-root',required=True);p.add_argument('--source',required=True);p.add_argument('--target',required=True);p.add_argument('--python-sha256',required=True);q=p.parse_args(argv);b=Budget();admission=admit_owner(q,b)
 need(re.fullmatch('[a-f0-9]{64}',q.python_sha256),'QA_MANIFEST_RUNTIME_PIN');runtime=held(Path(sys.executable).resolve(),b,33554432);need(hashlib.sha256(runtime).hexdigest()==q.python_sha256,'QA_MANIFEST_PINNED_PYTHON')
 android=Path(q.android_root).resolve(strict=True);inp=Path(q.input).resolve(strict=True);out=Path(q.output_root);need(out.is_absolute()and out==android/('app/build/generated/caseops-qa-observer/'+q.source+'/localAcceptance')and inp.is_relative_to(android/'app/build/intermediates'),'QA_MANIFEST_ARTIFACT_SCOPE')
 manifest_out=Path(q.manifest_output);need(manifest_out.is_absolute()and manifest_out.is_relative_to(android/'app/build/intermediates')and manifest_out.name=='AndroidManifest.xml','QA_MANIFEST_WIRED_OUTPUT_SCOPE')
 raw=held(inp,b,1048576);xml,java,audit=transform(raw,q.target,q.source);audit.update({'runtimeSha256':q.python_sha256,'runtimeObservedBytes':len(runtime),'transformProcessPid':os.getpid(),'transformParentPid':os.getppid(),'ownerAdmission':admission,'sourceObservedBytes':b.bytes,'metadataOperations':b.entries})
 for name,data in java.items():write_exact(out/'java'/Path(*PKG.split('.'))/name,data,b,android)
 write_exact(manifest_out,xml,b,android);write_exact(out/'receipt.json',(json.dumps(audit,indent=2)+'\n').encode(),b,android)
if __name__=='__main__':main(sys.argv[1:])
