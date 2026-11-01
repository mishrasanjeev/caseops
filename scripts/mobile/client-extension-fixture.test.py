"""Actual fixture functions with deterministic HTTP doubles; no API/SQL/native calls."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import os
import sys

HERE=Path(__file__).resolve().parent
p=ModuleType('actual_client_fixture');exec(compile((HERE/'local-client-extension-fixture.py').read_bytes(),str(HERE/'local-client-extension-fixture.py'),'exec'),p.__dict__)
def uid(n):return '00000000-0000-4000-8000-'+format(n,'012x')
def response(value,status=200):
    content=json.dumps(value).encode();return SimpleNamespace(status_code=status,content=content,json=lambda:value)
class Producer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.owner_calls=0;self.public_calls=[];self.calls=[];self.counter=100;self.matters={}
        second={'observed':True,'sourceSha':'a'*40,'noPaidMarker':'no-paid-providers','companyId':uid(90),'matter':{'id':uid(91),'code':'SECOND','search':'SECOND','title':'Synthetic second'}}
        file=self.root/'second.json';b=json.dumps(second).encode();file.write_bytes(b)
        self.q={'kind':'native-client-normal-api-producer','schemaVersion':1,'readyForLive':True,'preparedOnly':False,'productionAccessed':False,'noPaidMarker':'no-paid-providers','automaticRetry':False,'sourceSha':'a'*40,'backendRevision':'owned-api','webRevision':'owned-web','expiresAt':1100,'datasetId':uid(1),'companyId':uid(2),'membershipId':uid(3),'userId':uid(4),'cameraMatterId':uid(5),'byteSourceId':uid(6),'byteSourceSha256':'b'*64,'byteSourceText':'Synthetic source','companySlug':'test-mobile-cx','platform':'ios','workflowDomain':'simulator','hearingDate':'2026-10-28','actualBinaryVersion':'1.0.0','floorVersion':'1.0.1','secondMatterEvidence':{'path':str(file),'sha256':hashlib.sha256(b).hexdigest()},'retainedRows':[{'id':uid(7),'kind':'oversize'},{'id':uid(8),'kind':'legacy-json'}],'scannerConfigurationEvidence':{'path':str(self.root/'scanner.json'),'sha256':'c'*64}}
        self.env={'CASEOPS_NATIVE_CLIENT_DATASET_GO':'EXPLICIT_OWNED_SYNTHETIC_PRODUCER','CASEOPS_ENV':'local','CASEOPS_LLM_PROVIDER':'mock','CASEOPS_RELEASE_SHA':'a'*40,'K_REVISION':'owned-api'}
        self.public=SimpleNamespace(get=self.public_get)
    def public_get(self,url,**kwargs):
        self.public_calls.append((url,kwargs));return response({'release_sha':'a'*40,'revision':'owned-api'if url.startswith('http://api:8000')else'owned-web'})
    def owner(self):self.owner_calls+=1;return SimpleNamespace(request=self.request)
    def request(self,method,route,**kwargs):
        self.calls.append((method,route,kwargs));body=kwargs.get('json',{});self.counter+=1
        if route=='/api/auth/me':return response({'user':{'id':uid(4),'is_active':True},'company':{'id':uid(2),'slug':'test-mobile-cx'},'membership':{'id':uid(3),'is_active':True}})
        if route=='/api/matters/'+uid(5):return response({'id':uid(5),'company_id':uid(2),'is_active':True,'matter_code':'CAM','title':'Synthetic camera'})
        if route.endswith('/workspace'):return response({'attachments':[{'id':uid(6),'matter_id':uid(5),'sha256_hex':'b'*64}]})
        if route=='/api/matters/':
            value={**body,'id':uid(self.counter),'company_id':uid(2),'lifecycle_version':1,'is_active':True};self.matters[value['id']]=value;return response(value)
        parts=route.split('/')
        if method=='GET':return response({'scope':{'company_id':uid(2),'matter_id':next(iter(self.matters))},'read_state':'available','record':{'title':'Synthetic'},'items':[]})
        if route.endswith('/recommendations'):return response({'id':uid(self.counter),'matter_id':parts[3],'options':[{'id':uid(300)}],'review_required':True})
        if route.endswith('/decisions'):return response({'id':parts[3],'status':'deferred'})
        if route.endswith('/hearings'):return response({'id':uid(self.counter),'matter_id':parts[3]})
        if route.endswith('/pack'):return response({'id':uid(self.counter),'matter_id':parts[3],'hearing_id':parts[5],'items':[{'id':uid(301),'source_ref':'opaque:synthetic'}],'status':'draft','review_required':True})
        if route.endswith('/review'):return response({'id':parts[5],'status':'reviewed'})
        raise AssertionError('unexpected fixed recipe route')
    def run_producer(self,q=None,env=None):return p.produce_normal(q or self.q,root=self.root,environment=env or self.env,http=self.public,owner=self.owner,now=lambda:1000)
    def test_actual_canonical_local_revision_and_complete_normal_api_transitions(self):
        result=self.run_producer();value=json.loads(Path(result['datasetEvidence']['path']).read_bytes())
        self.assertEqual(value['counts'],{'requests':19,'posts':12});self.assertEqual(len(value['acknowledgements']),12);self.assertEqual(self.owner_calls,1)
        self.assertEqual(sum(m=='POST'and r.endswith('/recommendations')for m,r,_ in self.calls),2)
        self.assertEqual(sum(m=='POST'and r.endswith('/pack')for m,r,_ in self.calls),2)
        self.assertEqual(sum(m=='POST'and r.endswith('/review')for m,r,_ in self.calls),1)
        self.assertEqual([x.get('status')for x in value['cx']['readthrough']['packStates']],['draft','reviewed',None]);self.assertFalse(value['directDatabaseWrites']);self.assertEqual(value['llmProvider'],'mock')
        self.assertTrue(all(k['headers']=={'X-CaseOps-Automated-Test':'no-paid-providers'}for _,k in self.public_calls))
        for method,route,kwargs in self.calls:
            if method=='POST'and route.endswith('/hearings'):
                self.assertEqual(kwargs['json']['expected_lifecycle_version'],1);self.assertEqual(kwargs['json']['reminder_channels'],['in_app']);self.assertEqual(kwargs['json']['reminder_recipient_membership_ids'],[])
        self.assertEqual(json.loads(Path(result['validSiblingEvidence']['path']).read_bytes())['kind'],'normal-api-synthetic-recommendation')
    def test_cloud_foreign_revision_nonmock_pending_expired_refuse_before_private_or_http(self):
        for change in ({'K_SERVICE':'cloud'},{'K_REVISION':'foreign'},{'CASEOPS_LLM_PROVIDER':'openai'}):
            with self.subTest(change=change),self.assertRaises(AssertionError):self.run_producer(env={**self.env,**change})
        for change in ({'preparedOnly':True},{'expiresAt':999},{'sourceSha':'f'*40}):
            with self.subTest(change=change),self.assertRaises(AssertionError):self.run_producer(q={**self.q,**change})
        self.assertEqual(self.owner_calls,0);self.assertEqual(self.public_calls,[]);self.assertEqual(self.calls,[])
    def test_unknown_post_keeps_first_claim_and_ack_without_replay(self):
        original=self.request
        def unknown(method,route,**kwargs):
            if method=='POST'and route.endswith('/recommendations'):raise TimeoutError('synthetic unknown')
            return original(method,route,**kwargs)
        self.request=unknown
        with self.assertRaises(TimeoutError):self.run_producer()
        self.assertEqual(len(list(self.root.glob('*.claim.json'))),1);self.assertEqual(len(list(self.root.glob('*.normal-ack-*.json'))),3)
        count=len(self.calls)
        with self.assertRaises(FileExistsError):self.run_producer()
        self.assertEqual(len(self.calls),count);self.assertEqual(self.owner_calls,1)
    def test_retained_plan_is_separate_exact_two_invalid_rows_without_claiming_completion(self):
        q={'companyId':uid(2),'matterId':uid(10),'membershipId':uid(3),'rows':self.q['retainedRows']}
        rows=p.retained_values(q);self.assertGreater(len(rows[0]['rationale']),16384);self.assertEqual(rows[1]['assumptions_json'],'[')
        self.assertEqual([x['id']for x in rows],[uid(7),uid(8)]);self.assertEqual(self.calls,[])
    def test_existing_cli_dispatches_normal_login_mfa_with_marked_strict_clients_without_replaying_owner(self):
        credential=self.root/'owner.json';raw=json.dumps({'email':'synthetic@example.invalid','password':'synthetic-offline-only','company_slug':self.q['companySlug'],'totp_secret':'SYNTHETICOFFLINE'}).encode();credential.write_bytes(raw);credential.chmod(0o600)
        q={**self.q,'credentialEvidence':{'path':str(credential),'sha256':hashlib.sha256(raw).hexdigest(),'uid':os.getuid()}};request=self.root/'request.json';data=json.dumps(q).encode();request.write_bytes(data)
        clients=[];requests=[]
        class Client:
            def __init__(client,**options):
                client.options=options;client.headers=dict(options['headers']);client.cookies=SimpleNamespace(clear=lambda:requests.append(('clear-cookies',)));clients.append(client)
            def __enter__(client):return client
            def __exit__(client,*args):requests.append(('closed',client is clients[-1]))
            def post(client,route,**options):
                requests.append((route,options,dict(client.headers)))
                if route=='/api/auth/login':return response({'access_token':'offline-response-token','user':{'id':uid(4)},'membership':{'id':uid(3)},'company':{'id':uid(2)}})
                if route=='/api/auth/mfa/step-up':return response({'status':'verified'})
                raise AssertionError('unexpected offline CLI route')
        fake_http=SimpleNamespace(Client=Client);fake_otp=SimpleNamespace(TOTP=lambda value:SimpleNamespace(now=lambda:'123456'))
        def normal(request,*,root,environment,http,owner,now):
            self.assertEqual(request,q);actor=owner();self.assertIs(actor,clients[1]);self.assertEqual(actor.headers['Authorization'],'Bearer offline-response-token')
            with self.assertRaises(AssertionError):owner()
            return {'offlineDispatch':'normal','actualNativeAcceptance':False}
        with patch.dict(os.environ,{**self.env,'CASEOPS_MOBILE_STATE':str(self.root)}),patch.dict(sys.modules,{'httpx':fake_http,'pyotp':fake_otp}),patch.object(p,'produce_normal',normal),patch.object(p,'produce',side_effect=AssertionError('retained dispatch must stay separate')):
            result=p.main(str(request),hashlib.sha256(data).hexdigest())
        self.assertEqual(result['offlineDispatch'],'normal');self.assertEqual(len(clients),2)
        for client in clients:
            self.assertEqual(client.options['headers'],{'X-CaseOps-Automated-Test':'no-paid-providers'});self.assertIs(client.options['verify'],True);self.assertIs(client.options['follow_redirects'],False);self.assertIs(client.options['trust_env'],False)
        routes=[x for x in requests if x[0].startswith('/api/')];self.assertEqual([x[0]for x in routes],['/api/auth/login','/api/auth/mfa/step-up'])
        self.assertTrue(all(x[2]['X-CaseOps-Automated-Test']=='no-paid-providers'for x in routes));self.assertTrue(all(x[1]['timeout']==5 for x in routes))
    def test_private_reader_rejects_boolean_uid_and_erases_held_bytes_on_success_and_parse_failure(self):
        file=self.root/'held.json';file.write_text('{"password":"offline-only"}');file.chmod(0o600);raw=file.read_bytes();ref={'path':str(file),'sha256':hashlib.sha256(raw).hexdigest(),'uid':os.getuid()}
        for value in (True,False,-1,None):
            with self.subTest(uid=value),patch.object(Path,'lstat',side_effect=AssertionError('INVALID_UID_MUST_NOT_REACH_FILESYSTEM')),self.assertRaisesRegex(AssertionError,'^$'):
                p.held_json({**ref,'uid':value},self.root,private=True)
        captured=[]
        class Held(bytearray):
            def __init__(self,*args):super().__init__(*args);captured.append(self)
        with patch.object(p,'bytearray',Held,create=True):self.assertEqual(p.held_json(ref,self.root,private=True),{'password':'offline-only'})
        self.assertTrue(captured);self.assertTrue(all(not any(value)for value in captured))
        file.write_bytes(b'{invalid');ref['sha256']=hashlib.sha256(file.read_bytes()).hexdigest();captured.clear()
        with patch.object(p,'bytearray',Held,create=True),self.assertRaises(json.JSONDecodeError):p.held_json(ref,self.root,private=True)
        self.assertTrue(captured);self.assertTrue(all(not any(value)for value in captured))
if __name__=='__main__':unittest.main(verbosity=2)
