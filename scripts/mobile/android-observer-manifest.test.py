import importlib.util, pathlib, tempfile, unittest, os, types, hashlib, subprocess, sys, json, ast, re
P=pathlib.Path(__file__).with_name('android-observer-manifest.py');spec=importlib.util.spec_from_file_location('observer_manifest',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
RAW=b'<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="ai.caseops.mobile.dev.localacceptance"><uses-permission android:name="android.permission.CAMERA"/><application android:name="ai.caseops.mobile.dev.MainApplication" android:debuggable="false" android:allowBackup="false" android:appComponentFactory="reviewed.actual.Factory"><provider android:name="reviewed.actual.Provider" android:authorities="owned"><meta-data android:name="reviewed.actual.Initializer" android:value="androidx.startup"/></provider><activity android:name="ai.caseops.mobile.dev.MainActivity"/></application></manifest>'
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
   android=pathlib.Path(d).resolve()/'android';inp=android/'app/build/intermediates/merged_manifest/localAcceptance/AndroidManifest.xml';inp.parent.mkdir(parents=True);inp.write_bytes(RAW);out=android/('app/build/generated/caseops-qa-observer/'+'a'*40+'/localAcceptance');manifest=android/'app/build/intermediates/caseopsQaObserverManifest/AndroidManifest.xml';(out/'java/ai/caseops/mobile/qa').mkdir(parents=True);manifest.parent.mkdir(parents=True);runtime=pathlib.Path(sys.executable).resolve();pin=hashlib.sha256(runtime.read_bytes()).hexdigest()
   result=subprocess.run([str(runtime),'-I','-B',str(P),'--input',str(inp),'--output-root',str(out),'--manifest-output',str(manifest),'--android-root',str(android),'--source','a'*40,'--target',m.APP,'--python-sha256',pin],capture_output=True,timeout=15)
   self.assertEqual(result.returncode,0,result.stderr.decode());self.assertEqual(result.stdout,b'');receipt=json.loads((out/'receipt.json').read_bytes());self.assertEqual(receipt['runtimeSha256'],pin);self.assertEqual(receipt['inputSha256'],hashlib.sha256(RAW).hexdigest());self.assertEqual(receipt['outputSha256'],hashlib.sha256(manifest.read_bytes()).hexdigest());self.assertTrue((out/'java/ai/caseops/mobile/qa/QaObserverFactory.java').is_file());self.assertFalse(receipt['productionTransform'])
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
