import importlib.util, pathlib, tempfile, unittest, os, types, hashlib, subprocess, sys, json, ast, re
P=pathlib.Path(__file__).with_name('android-observer-manifest.py');spec=importlib.util.spec_from_file_location('observer_manifest',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
RAW=b'<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="ai.caseops.mobile.dev.localacceptance"><uses-permission android:name="android.permission.CAMERA"/><application android:name="ai.caseops.mobile.dev.MainApplication" android:debuggable="false" android:allowBackup="false" android:appComponentFactory="reviewed.actual.Factory"><provider android:name="reviewed.actual.Provider" android:authorities="owned"><meta-data android:name="reviewed.actual.Initializer" android:value="androidx.startup"/></provider><activity android:name="ai.caseops.mobile.dev.MainActivity"/></application></manifest>'

def owned_cli_runtime(root,b):
 # Only this test fixture may copy public interpreter bytes. Production held()
 # keeps its current-owner/single-link rule unchanged.
 import stat,time,sysconfig,argparse,xml.etree.ElementTree as ET,_hashlib
 source=pathlib.Path(sys.executable).resolve();ns=m.namespace(source,b);fd=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
 try:
  first=os.fstat(fd);named=source.lstat();b.charge();b.charge();m.need(stat.S_ISREG(first.st_mode)and stat.S_ISREG(named.st_mode)and not stat.S_ISLNK(named.st_mode)and m.named_matches_fd(named,first)and 0<first.st_size<=33554432,'TEST_RUNTIME_PUBLIC_DESCRIPTOR');raw=bytearray()
  while len(raw)<=first.st_size:
   part=os.read(fd,min(65536,first.st_size+1-len(raw)));b.charge(len(part))
   if not part:break
   raw.extend(part)
  source_after_fd=os.fstat(fd);b.charge();source_after_named=source.lstat();b.charge();m.need(len(raw)==first.st_size and m.same(first,source_after_fd)and m.same(named,source_after_named)and m.namespace(source,b)==ns,'TEST_RUNTIME_PUBLIC_CHANGED');pin=hashlib.sha256(raw).hexdigest();runtime=source;copied=first.st_uid!=m.owner()or first.st_nlink!=1
  if copied:
   m.need(sys.platform=='linux'and source.is_relative_to('/usr')and sys.prefix==sys.base_prefix,'TEST_RUNTIME_COPY_ONLY_SYSTEM_LINUX')
   try:m.held(source,m.Budget(),33554432)
   except RuntimeError as error:m.need(str(error)=='QA_MANIFEST_OWNED_FILE','TEST_RUNTIME_ORIGINAL_REFUSAL')
   else:raise AssertionError('TEST_RUNTIME_ORIGINAL_WAS_NOT_REFUSED')
   parent=root/'owned-runtime';parent.mkdir(mode=0o700);runtime=parent/source.name;target_ns=m.namespace(runtime,b);target=os.open(runtime,os.O_RDWR|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o700)
   try:
    created=os.fstat(target);b.charge();m.need(stat.S_ISREG(created.st_mode)and created.st_uid==m.owner()and created.st_nlink==1 and created.st_size==0,'TEST_RUNTIME_EXCLUSIVE_DESCRIPTOR');offset=0
    while offset<len(raw):
     width=os.write(target,memoryview(raw)[offset:offset+65536]);b.charge(width);m.need(width>0,'TEST_RUNTIME_COPY_PROGRESS');offset+=width
    os.fchmod(target,0o700);os.fsync(target);final=os.fstat(target);b.charge();m.need(final.st_size==len(raw)and stat.S_IMODE(final.st_mode)==0o700 and all(getattr(created,k)==getattr(final,k)for k in('st_dev','st_ino','st_uid','st_gid','st_nlink')),'TEST_RUNTIME_COPY_IDENTITY');os.lseek(target,0,os.SEEK_SET);back=bytearray()
    while len(back)<=len(raw):
     part=os.read(target,min(65536,len(raw)+1-len(back)));b.charge(len(part))
     if not part:break
     back.extend(part)
    last_named=runtime.lstat();b.charge();last_fd=os.fstat(target);b.charge();m.need(back==raw and m.same(final,last_fd)and m.named_matches_fd(last_named,final)and m.namespace(runtime,b)==target_ns,'TEST_RUNTIME_COPY_READBACK')
   finally:os.close(target)
  source_final_fd=os.fstat(fd);b.charge();source_final_named=source.lstat();b.charge();m.need(m.same(first,source_final_fd)and m.same(named,source_final_named)and m.namespace(source,b)==ns,'TEST_RUNTIME_PUBLIC_FINAL_CHANGED')
 finally:os.close(fd)
 identity_source="def module_identity(value):\n name=value.__name__;file=getattr(value,'__file__',None)\n if file is not None:\n  if type(file)is not str or not file or not pathlib.Path(file).is_absolute():raise RuntimeError('TEST_RUNTIME_MODULE_FILE_ORIGIN')\n  return {'kind':'file','name':name,'origin':str(pathlib.Path(file).resolve())}\n spec=getattr(value,'__spec__',None)\n if spec is None or spec.origin!='built-in' or name not in sys.builtin_module_names:raise RuntimeError('TEST_RUNTIME_MODULE_BUILTIN_ORIGIN')\n return {'kind':'built-in','name':name,'origin':'built-in'}\n"
 identity_scope={'sys':sys,'pathlib':pathlib};exec(compile(identity_source,'fixture-runtime-module-identity','exec'),identity_scope);identity=identity_scope['module_identity']
 expected={'prefix':sys.prefix,'basePrefix':sys.base_prefix,'stdlib':sysconfig.get_path('stdlib'),'libdir':sysconfig.get_config_var('LIBDIR'),'ldlibrary':sysconfig.get_config_var('LDLIBRARY'),'shared':sysconfig.get_config_var('Py_ENABLE_SHARED'),'modules':{x.__name__:identity(x)for x in(argparse,hashlib,json,ET,_hashlib)}}
 if copied:
  # The same literal identity function distinguishes exact file origins from
  # actual interpreter built-ins in both the parent and copied executable.
  code="import argparse,hashlib,json,pathlib,sys,sysconfig,xml.etree.ElementTree as ET,_hashlib\n"+identity_source+"\nprint(json.dumps({'prefix':sys.prefix,'basePrefix':sys.base_prefix,'stdlib':sysconfig.get_path('stdlib'),'libdir':sysconfig.get_config_var('LIBDIR'),'ldlibrary':sysconfig.get_config_var('LDLIBRARY'),'shared':sysconfig.get_config_var('Py_ENABLE_SHARED'),'modules':{x.__name__:module_identity(x)for x in(argparse,hashlib,json,ET,_hashlib)}}))"
  remaining=b.end-time.monotonic();m.need(remaining>0,'TEST_RUNTIME_SHARED_DEADLINE');probe=subprocess.run([str(runtime),'-I','-B','-c',code],capture_output=True,timeout=remaining);m.need(probe.returncode==0 and probe.stderr==b''and len(probe.stdout)<=16384,'TEST_RUNTIME_STDLIB_PROBE');b.charge(len(probe.stdout));m.need(json.loads(probe.stdout)==expected,'TEST_RUNTIME_STDLIB_LIBRARY_EQUIVALENCE')
 print('QA_MANIFEST_TEST_RUNTIME '+json.dumps({'sourceUid':first.st_uid,'ownerUid':m.owner(),'sourceNlink':first.st_nlink,'sourceBytes':first.st_size,'copied':copied,'runtimeSha256':pin,'prefix':expected['prefix'],'stdlib':expected['stdlib'],'libdir':expected['libdir'],'ldlibrary':expected['ldlibrary'],'shared':expected['shared'],'modules':expected['modules']},sort_keys=True),file=sys.stderr)
 return runtime,pin

class Manifest(unittest.TestCase):
 def transform(self,raw=RAW):return m.transform(raw,m.APP,'a'*40)
 def test_actual_merged_factory_is_recorded_and_delegated(self):
  xml,java,a=self.transform();self.assertEqual(a['effectiveRecordedBaseFactory'],'reviewed.actual.Factory');self.assertEqual(a['originalInitializerRoster'][0]['name'],'reviewed.actual.Initializer');self.assertIn(b'new reviewed.actual.Factory()',java['QaObserverFactory.java']);self.assertIn(b'android.permission.CAMERA',xml)
 def test_absent_factory_records_framework_effective_default(self):
  _,_,a=self.transform(RAW.replace(b' android:appComponentFactory="reviewed.actual.Factory"',b''));self.assertFalse(a['rawBaseFactoryPresent']);self.assertEqual(a['effectiveRecordedBaseFactory'],'android.app.AppComponentFactory')
 def test_cold_observer_never_constructs_base_or_main(self):
  _,java,_=self.transform();s=java['QaObserverFactory.java'].decode();self.assertIn('return observer()?c:base().instantiateClassLoader(c,info)',s);self.assertIn('if(observer()) return new android.app.Application();',s);self.assertIn('QA_OBSERVER_BASE_CONSTRUCTION_REFUSED',s);self.assertNotIn('new ai.caseops.mobile.dev.MainApplication',s)
 def test_main_gate_precedes_providers_and_original_oncreate(self):
  _,java,_=self.transform();s=java['QaMainApplication.java'].decode();self.assertIn('attachBaseContext',s);self.assertIn('super.attachBaseContext(base);',s);self.assertIn('&& !QaLifecycleWitness.install(this))',s);self.assertNotIn('onCreate()',s)
 def test_exact_source_metadata_and_signature_permission(self):
  xml,_,a=self.transform();self.assertIn(('android:value="'+'a'*40+'"').encode(),xml);self.assertIn(b'protectionLevel="signature"',xml);self.assertIn(b'android:process=":privacyobserver"',xml);self.assertFalse(a['productionTransform'])
 def test_production_target_refuses(self):
  with self.assertRaisesRegex(RuntimeError,'QA_ONLY'):m.transform(RAW,'ai.caseops.mobile.dev','a'*40)
 def test_debuggable_refuses(self):
  with self.assertRaisesRegex(RuntimeError,'NONDEBUGGABLE'):self.transform(RAW.replace(b'debuggable="false"',b'debuggable="true"'))
 def test_observer_process_collision_refuses(self):
  with self.assertRaisesRegex(RuntimeError,'PROCESS_COLLISION'):self.transform(RAW.replace(b'<provider ',b'<provider android:process=":privacyobserver" '))
 def test_multiprocess_provider_refuses(self):
  with self.assertRaisesRegex(RuntimeError,'MULTIPROCESS_PROVIDER'):self.transform(RAW.replace(b'<provider ',b'<provider android:multiprocess="true" '))
 def test_entity_input_refuses(self):
  with self.assertRaisesRegex(RuntimeError,'DTD_REFUSED'):self.transform(b'<!DOCTYPE x>'+RAW)
 def test_same_fd_reader_refuses_link_and_closes(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d).resolve()/'one';p.write_bytes(b'public');self.assertEqual(m.held(p,m.Budget(),32),b'public');link=p.with_name('alias');link.symlink_to(p)
   with self.assertRaisesRegex(RuntimeError,'OWNED_FILE'):m.held(link,m.Budget(),32)
   os.link(p,p.with_name('hard'))
   with self.assertRaisesRegex(RuntimeError,'OWNED_FILE'):m.held(p,m.Budget(),32)
 def test_exclusive_output_preserves_failed_candidate(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d).resolve()/'owned';m.write_exact(p,b'first',m.Budget(),pathlib.Path(d).resolve())
   with self.assertRaisesRegex(RuntimeError,'STALE_OWNED'):m.write_exact(p,b'second',m.Budget(),pathlib.Path(d).resolve())
   self.assertEqual(p.read_bytes(),b'first')
 def test_actual_cli_binds_runtime_artifact_paths_source_and_generated_java(self):
  with tempfile.TemporaryDirectory()as d:
   android=pathlib.Path(d).resolve()/'android';inp=android/'app/build/intermediates/merged_manifest/localAcceptance/AndroidManifest.xml';inp.parent.mkdir(parents=True);inp.write_bytes(RAW);out=android/('app/build/generated/caseops-qa-observer/'+'a'*40+'/localAcceptance');manifest=android/'app/build/intermediates/caseopsQaObserverManifest/AndroidManifest.xml';(out/'java/ai/caseops/mobile/qa').mkdir(parents=True);manifest.parent.mkdir(parents=True);budget=m.Budget();runtime,pin=owned_cli_runtime(pathlib.Path(d).resolve(),budget)
   remaining=budget.end-__import__('time').monotonic();self.assertGreater(remaining,0)
   result=subprocess.run([str(runtime),'-I','-B',str(P),'--input',str(inp),'--output-root',str(out),'--manifest-output',str(manifest),'--android-root',str(android),'--source','a'*40,'--target',m.APP,'--python-sha256',pin],capture_output=True,timeout=remaining)
   self.assertLess(__import__('time').monotonic(),budget.end);self.assertEqual(result.returncode,0,result.stderr.decode());self.assertEqual(result.stdout,b'');receipt=json.loads((out/'receipt.json').read_bytes());self.assertEqual(receipt['runtimeSha256'],pin);self.assertEqual(receipt['inputSha256'],hashlib.sha256(RAW).hexdigest());self.assertEqual(receipt['outputSha256'],hashlib.sha256(manifest.read_bytes()).hexdigest());self.assertTrue((out/'java/ai/caseops/mobile/qa/QaObserverFactory.java').is_file());self.assertFalse(receipt['productionTransform'])
 def test_windows_device_exception_preserves_all_other_identity_fields(self):
  a=types.SimpleNamespace(**{k:1 for k in m.FIELDS});b=types.SimpleNamespace(**vars(a));b.st_dev=0;self.assertTrue(m.named_matches_fd(b,a,'nt'));self.assertFalse(m.named_matches_fd(b,a,'posix'));self.assertFalse(m.same(a,b));b.st_ino=2;self.assertFalse(m.named_matches_fd(b,a,'nt'))
 def test_nonzero_named_windows_device_mismatch_is_never_waived(self):
  a=types.SimpleNamespace(**{k:1 for k in m.FIELDS});b=types.SimpleNamespace(**vars(a));b.st_dev=2;self.assertFalse(m.named_matches_fd(a,b,'nt'));self.assertFalse(m.same(a,b))
 def test_full_fd_windows_device_and_all_identity_fields_stay_exact(self):
  a=types.SimpleNamespace(**{k:1 for k in m.FIELDS})
  for key in m.FIELDS:
   b=types.SimpleNamespace(**vars(a));setattr(b,key,2);self.assertFalse(m.same(a,b),key)
 def test_named_devzero_never_waives_owner_or_inode(self):
  a=types.SimpleNamespace(**{k:1 for k in m.FIELDS});named=types.SimpleNamespace(**vars(a));named.st_dev=0
  for key in('st_uid','st_ino','st_gid','st_mode','st_nlink'):
   changed=types.SimpleNamespace(**vars(named));setattr(changed,key,2);self.assertFalse(m.named_matches_fd(changed,a,'nt'),key)
 def test_missing_output_parent_is_refusal_without_directory_creation(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d).resolve();p=root/'missing'/'file'
   with self.assertRaises(FileNotFoundError):m.write_exact(p,b'public',m.Budget(),root)
   self.assertFalse(p.parent.exists())
 def test_symlink_output_ancestor_cannot_create_outside_directory_or_file(self):
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d).resolve();admitted=root/'admitted';admitted.mkdir();outside=root/'outside';outside.mkdir();(admitted/'link').symlink_to(outside,target_is_directory=True)
   for p in(admitted/'link'/'missing'/'file',admitted/'link'/'file'):
    with self.assertRaises((RuntimeError,FileNotFoundError)):m.write_exact(p,b'public',m.Budget(),admitted)
   self.assertEqual(list(outside.iterdir()),[])
 def test_embedded_bootstrap_uses_full_fd_frames_and_only_named_devzero_exception(self):
  cjs=P.parents[2]/'apps/mobile/plugins/qa-observer.cjs';raw=cjs.read_text();source=re.search(r'const BOOT = String.raw`(.*?)`;',raw,re.S).group(1);tree=ast.parse(source);selected=[n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name in('ident','named_matches_fd')];self.assertEqual(len(selected),2);scope={'os':os};exec(compile(ast.Module(body=selected,type_ignores=[]),'held-bootstrap-functions','exec'),scope)
  fd=types.SimpleNamespace(**{k:1 for k in m.FIELDS});named=types.SimpleNamespace(**vars(fd));named.st_dev=0;self.assertTrue(scope['named_matches_fd'](named,fd,'nt'));self.assertFalse(scope['named_matches_fd'](fd,types.SimpleNamespace(**{**vars(fd),'st_dev':2}),'nt'))
  for field in m.FIELDS:
   changed=types.SimpleNamespace(**{**vars(fd),field:2});self.assertNotEqual(scope['ident'](fd),scope['ident'](changed))
 def test_owner_channel_absence_has_no_filesystem_or_runtime_sideeffects(self):
  previous=os.environ.pop('CASEOPS_ANDROID_OBSERVER_ADMISSION',None);original=m.held;m.held=lambda *args:(_ for _ in()).throw(AssertionError('unexpected filesystem read'))
  try:self.assertIsNone(m.admit_owner(types.SimpleNamespace(),m.Budget()))
  finally:
   m.held=original
   if previous is not None:os.environ['CASEOPS_ANDROID_OBSERVER_ADMISSION']=previous
 def test_bootstrap_start_keeps_owner_ack_inside_original_fifteen_seconds(self):
  import time
  m._CASEOPS_OBSERVER_STARTED_MONOTONIC=time.monotonic()-2
  try:self.assertLessEqual(m.Budget().end,time.monotonic()+13)
  finally:del m._CASEOPS_OBSERVER_STARTED_MONOTONIC
 def test_explicit_unsupported_owner_channel_refuses_before_paths_or_locks(self):
  previous=os.environ.get('CASEOPS_ANDROID_OBSERVER_ADMISSION');platform=m.os.name;os.environ['CASEOPS_ANDROID_OBSERVER_ADMISSION']='{}';m.os.name='nt'
  try:
   with self.assertRaisesRegex(RuntimeError,'OWNER_CHANNEL_PLATFORM'):m.admit_owner(types.SimpleNamespace(),m.Budget())
  finally:
   m.os.name=platform
   if previous is None:os.environ.pop('CASEOPS_ANDROID_OBSERVER_ADMISSION',None)
   else:os.environ['CASEOPS_ANDROID_OBSERVER_ADMISSION']=previous
 def test_same_fd_capture_never_adopts_post_close_identical_replacement(self):
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d).resolve()/'public';p.write_bytes(b'owned-public');original=m.os.close;before=p.stat().st_ino;done=[]
   def close(fd):
    original(fd)
    if not done:done.append(True);p.rename(p.with_name('retained'));p.write_bytes(b'owned-public')
   m.os.close=close
   try:raw,metadata=m.held(p,m.Budget(),64,capture=True)
   finally:m.os.close=original
   self.assertEqual(raw,b'owned-public');self.assertEqual(metadata[1],before);self.assertNotEqual(metadata[1],p.stat().st_ino)
if __name__=='__main__':unittest.main()
