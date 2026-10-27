"""Offline profile/protocol/loader controls; synthetic FS/HTTP doubles only."""
from pathlib import Path
from types import ModuleType,SimpleNamespace
from unittest.mock import patch
import unittest,json,hashlib,time,tempfile,os,sys
HERE=Path(__file__).resolve().parent
def load(name,file):
    m=ModuleType(name);m.__file__=str(HERE/file);exec(compile((HERE/file).read_bytes(),str(HERE/file),'exec'),m.__dict__);return m
p=load('qp_controls','local-queue-privacy-controls.py');g=load('qp_gateway','local-gateway.py')
def uid(n):return '00000000-0000-4000-8000-'+format(n,'012x')
def registration():
    actor=lambda n,c:{'companyId':uid(c),'membershipId':uid(n),'userId':uid(n+20),'credentialEvidence':{'path':'/synthetic/member.json','sha256':'a'*64,'uid':os.getuid()}}
    mid,tid=uid(10),uid(11);routes=['GET /api/matters/'+mid,'GET /api/matters/'+mid+'/tasks','PATCH /api/matters/'+mid+'/tasks/'+tid]
    recipes=[]
    for action in ('change','restore'):
        recipes.append({'id':action,'caseId':'QUEUE-01','capability':'changeAnchor','argumentsSha256':p.sha(p.canonical({'action':action})),
            'requests':[{'method':'GET','route':routes[0][4:],'expectedStatuses':[200]},{'method':'GET','route':routes[1][4:],'expectedStatuses':[200]},
                        {'method':'PATCH','route':routes[2][6:],'expectedStatuses':[200],'body':{'due_on':'2027-01-01','expected_lifecycle_version':{'response':'0.lifecycle_version'},'expected_updated_at':{'select':{'response':'1.tasks','where':{'id':tid},'field':'updated_at'}}}}]})
    return {'kind':'registered-queue-privacy-controls','profile':p.PROFILE,'schemaVersion':1,'observed':True,'readyForLive':True,'preparedOnly':False,
        'environment':'docker-integration','syntheticDataOnly':True,'noPaidMarker':'no-paid-providers','directDatabaseWrites':False,'nativeMutationsForwardedByControls':False,
        'sourceSha':'a'*40,'runId':'qp-'+uid(1),'expiresAt':time.time()+400,'baseImplementationSha256':p.BASE_SHA256,'implementationSha256':'b'*64,
        'capabilities':list(p.CAPABILITIES),'caseControlLimits':p.CASES,'registrationId':'a'*32,'companyId':uid(1),'syntheticIds':[uid(i)for i in range(1,40)],
        'actors':{'owner':actor(2,1),'member':actor(3,1),'second-company':actor(4,5)},'anchor':{'id':tid,'matterId':mid},
        'exactRoutes':['GET '+p.QUEUE,'GET '+p.PRIVACY,'POST '+p.PRIVACY,'GET /api/matters/'+mid+'/workspace'],'ownerExactRoutes':routes,'ownerRecipes':recipes,
        'backendRevision':'api-rev','webRevision':'web-rev','authorityEvidence':{'path':'/synthetic/authority.json','sha256':'a'*64,'uid':os.getuid()}}
class Owner:
    def __init__(self):self.closed=False;self.calls=[];self.restored=True
    def __call__(self,*args):self.calls.append(args);return {'status':200,'value':{'request':None}}
    def close(self):self.closed=True
    def restoration_complete(self):return self.restored
class Protocol(unittest.TestCase):
    def setUp(self):
        self.v=registration();self.owner=Owner();self.claims=[];self.events=[];self.journal=[]
        expected={k:self.v['actors']['member'][k]for k in ('userId','membershipId','companyId')}
        self.c=p.Controls(self.v,'a'*64,'b'*64,base=None,owner=self.owner,claim=self.claims.append,persist=self.events.append,close_journal=lambda:self.journal.append('closed'),principal=lambda _token:expected)
        self.n=0
    def call(self,cap,case='PRIVACY-01',args=None,identity=None):
        self.n+=1;q={'schemaVersion':1,'capability':cap,'caseId':case,'operationId':identity or self.v['runId']+':'+case+':'+str(self.n),'runId':self.v['runId'],'registrationSha256':'a'*64,'args':args or {}}
        return self.c.handle(json.dumps(q).encode(),marker='no-paid-providers',authority='b'*64)
    def arm(self):return self.call('armPrivacyAckLoss')['id']
    def native(self,body=None):
        self.body=json.dumps(body or {'operation_id':uid(90),'confirmation':'request_account_deletion'}).encode()
        self.c.validate_native_request('POST',p.PRIVACY,native=True,body=self.body,query='',authorization='Bearer cnat_SYNTHETIC')
        return self.c.before_native('POST',p.PRIVACY,native=True,request_id='native-request-1')
    def ack(self,intercept,status=202,value=None):
        self.value=value or {'id':uid(91),'operation_id':uid(90),'request_type':'account_deletion','status':'received','requested_at':'2026-10-27T12:00:00.123456Z','deletion_completed':False}
        return self.c.after_native('POST',p.PRIVACY,native=True,request_id='native-request-1',sequence=1,body=self.body,query='',status=status,data=json.dumps(self.value).encode(),intercept=intercept)
    def test_registration_positive_preserves_old_limits(self):
        p.validate_registration(self.v,source='a'*40,run=self.v['runId'],now=time.time());self.assertEqual(p.LIMITS['operations'],49);self.assertEqual(sum(p.CASES.values())+1,49)
        old=load('old_unchanged','local-v1-controls.py');self.assertEqual(old.LIMITS['operations'],264);self.assertEqual(sum(old.CASE_LIMITS.values())+1,255)
    def test_202_ack_loss_retains_exact_original_and_one_receipt_read(self):
        arm=self.arm();intercept=self.native();self.assertTrue(self.ack(intercept));r=self.call('readControlReceipt',args={'id':arm})
        self.assertTrue(r['upstreamAcknowledged']);self.assertEqual(r['upstreamStatus'],202);self.assertEqual(r['requestsForwarded'],1);self.assertEqual(r['responseObservation'],self.value)
        self.assertEqual(self.c.records[0]['bodyObservation']['keys'],['confirmation','operation_id']);self.assertNotIn('authorization',json.dumps(self.c.records).lower())
    def test_wrong_native_global_user_refuses_before_forward_and_claim_is_consumed(self):
        self.arm();self.c.principal=lambda _token:{'userId':uid(99),'membershipId':uid(3),'companyId':uid(1)}
        with self.assertRaisesRegex(AssertionError,'QP_NATIVE_SELF_REQUIRED'):self.native()
        self.assertEqual(len(self.claims),2)
        with self.assertRaises(AssertionError):self.c.before_native('POST',p.PRIVACY,native=True,request_id='no-forward')
        with self.assertRaisesRegex(AssertionError,'REPLAY'):self.native()
    def test_exact_body_keys_confirmation_uuid_and_byte_bound_before_claim(self):
        for body in ({'operation_id':uid(90),'confirmation':'other'},{'operation_id':'0'*36,'confirmation':'request_account_deletion'},
                     {'operation_id':uid(90),'confirmation':'request_account_deletion','subject_user_id':uid(4)}):
            old=len(self.claims)
            with self.assertRaises(AssertionError):self.native(body)
            self.assertEqual(len(self.claims),old)
    def test_one_native_attempt_cannot_rearm_or_replay(self):
        self.arm();intercept=self.native();self.ack(intercept)
        with self.assertRaises(AssertionError):self.native()
        with self.assertRaises(AssertionError):self.call('armPrivacyAckLoss')
    def test_wrong_receipt_operation_never_records_positive_ack(self):
        self.arm();i=self.native();bad={'id':uid(91),'operation_id':uid(92),'request_type':'account_deletion','status':'received','requested_at':'2026-10-27T12:00:00Z','deletion_completed':False}
        with self.assertRaises(AssertionError):self.ack(i,value=bad)
        self.assertFalse(i['arm']['upstreamAcknowledged']);self.assertTrue(self.c.privacy_attempted)
    def test_failure_status_keeps_original_failure_and_never_withholds_as_success(self):
        self.arm();i=self.native();self.assertFalse(self.ack(i,status=500));self.assertEqual(self.c.records[0]['status'],500);self.assertFalse(i['arm']['upstreamAcknowledged']);self.assertFalse(self.c.should_withhold(i,500))
    def test_receipt_does_not_claim_deletion_or_accept_bad_utc(self):
        good={'id':uid(91),'operation_id':uid(90),'request_type':'account_deletion','status':'received','requested_at':'2026-10-27T12:00:00Z','deletion_completed':False}
        for edit in (lambda d:d.update(deletion_completed=True),lambda d:d.update(requested_at='2026-10-27T12:00:00'),lambda d:d.update(status='completed')):
            value=dict(good);edit(value)
            with self.assertRaises(AssertionError):p.receipt(value)
    def test_registered92_plus_two_native_ids_preserves96_ceiling(self):
        self.v['syntheticIds']=[uid(i)for i in range(1,93)];self.c.known_ids=set(self.v['syntheticIds']);p.validate_registration(self.v,source='a'*40,run=self.v['runId'],now=time.time())
        self.arm();i=self.native({'operation_id':uid(94),'confirmation':'request_account_deletion'});self.ack(i,value={'id':uid(95),'operation_id':uid(94),'request_type':'account_deletion','status':'received','requested_at':'2026-10-27T12:00:00Z','deletion_completed':False});self.assertEqual(len(self.c.known_ids),94)
        self.v['syntheticIds'].append(uid(93))
        with self.assertRaises(AssertionError):p.validate_registration(self.v,source='a'*40,run=self.v['runId'],now=time.time())
    def test_cross_case_capability_and_unregistered_route_never_reach_owner(self):
        with self.assertRaises(AssertionError):self.call('armPrivacyAckLoss',case='QUEUE-01')
        with self.assertRaises(AssertionError):self.call('readNativeRequest',args={'method':'POST','route':'/api/account/other','afterSequence':0})
        self.assertEqual(self.owner.calls,[])
    def test_24_per_case_plus_single_final_cleanup_is49_not_hidden_polls(self):
        for case in p.CASES:
            for _ in range(24):self.call('readNativeRequest',case,args={'method':'GET','route':p.PRIVACY,'afterSequence':0})
            with self.assertRaises(AssertionError):self.call('readNativeRequest',case,args={'method':'GET','route':p.PRIVACY,'afterSequence':0})
        result=self.call('closeRunControls');self.assertTrue(result['authorityCleared']);self.assertEqual(len(self.c.operations),49);self.assertTrue(self.owner.closed);self.assertEqual(self.journal,['closed'])
    def test_final_cleanup_composes_with_real_owned_fd_journal(self):
        base=load('journal_base','local-v1-controls.py')
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw).resolve();persist,close=base.create_journal(root,'e'*32)
            self.c.persist=persist;self.c.close_journal=close
            try:result=self.call('closeRunControls')
            finally:close()
            rows=[json.loads(line)for line in (root/('v1-control-events-'+'e'*32+'.jsonl')).read_text().splitlines()]
            self.assertEqual([r['type']for r in rows],['qp_control_started','qp_control_completed'])
            self.assertTrue(result['journalClosed']);self.assertTrue(self.c.closed)
            with self.assertRaises(AssertionError):persist({'type':'after_close_forbidden'})
    def test_original_native_202_is_durable_before_ack_loss_is_authorized(self):
        base=load('ack_journal_base','local-v1-controls.py')
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw).resolve();persist,close=base.create_journal(root,'f'*32)
            self.c.persist=persist;self.c.close_journal=close
            try:
                self.arm();intercept=self.native();withheld=self.ack(intercept)
                rows=[json.loads(line)for line in (root/('v1-control-events-'+'f'*32+'.jsonl')).read_text().splitlines()]
                ack=[r for r in rows if r['type']=='qp_native_request_observed']
                self.assertEqual(len(ack),1);self.assertEqual(ack[0]['status'],202);self.assertEqual(ack[0]['responseObservation'],self.value)
                self.assertTrue(withheld);self.assertTrue(self.c.should_withhold(intercept,202))
                self.assertNotIn('authorization',json.dumps(rows).lower())
            finally:close()
    def test_ack_journal_write_failure_keeps_consumed_claim_without_false_ack_loss_or_replay(self):
        base=load('failed_ack_journal_base','local-v1-controls.py')
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw).resolve();persist,close=base.create_journal(root,'d'*32)
            self.c.persist=persist;self.c.close_journal=close
            try:
                self.arm();intercept=self.native()
                with patch.object(base.os,'write',side_effect=OSError('SYNTHETIC_WRITE_FAILED')),self.assertRaises(OSError):self.ack(intercept)
                self.assertTrue(self.c.privacy_attempted);self.assertFalse(intercept['arm']['upstreamAcknowledged'])
                self.assertFalse(self.c.should_withhold(intercept,202));self.assertEqual(self.c.records,[])
                with self.assertRaises(AssertionError):self.native()
            finally:close()
    def test_real_gateway_refuses_web_cookie_and_missing_authority_privacy_posts_before_upstream(self):
        import http.client,threading
        connection=http.client.HTTPConnection
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw).resolve();(root/'gateway-routes.json').write_text(json.dumps({'routes':['POST '+p.PRIVACY]}))
            with patch.dict(os.environ,{'CASEOPS_MOBILE_V1_CONTROLS':'0'}):gateway=g.Gateway(root)
            gateway.v1=self.c;server=g.ThreadingHTTPServer(('127.0.0.1',0),gateway.handler());thread=threading.Thread(target=server.serve_forever);thread.start();forwarded=[]
            self.arm();before_claims=list(self.claims)
            class Upstream:
                def __init__(self,*_,**__):pass
                def request(self,*args,**kwargs):forwarded.append(args);raise AssertionError('NO_UPSTREAM_ALLOWED')
                def close(self):pass
            try:
                for headers in ({},{'Cookie':'synthetic-cookie'},{'Authorization':'Bearer cnat_SYNTHETIC','Cookie':'synthetic-cookie'},{'Authorization':'Bearer web_SYNTHETIC'},{'Authorization':'Bearer cnat_SYNTHETIC','Cookie':''}):
                    with patch.object(g.http.client,'HTTPConnection',Upstream):
                        client=connection('127.0.0.1',server.server_port,timeout=2)
                        try:
                            client.request('POST',p.PRIVACY,body=json.dumps({'operation_id':uid(90),'confirmation':'request_account_deletion'}),headers={'X-CaseOps-Automated-Test':'no-paid-providers',**headers})
                            response=client.getresponse();self.assertEqual(response.status,502);response.read()
                        finally:client.close()
                self.assertEqual(forwarded,[]);self.assertEqual(self.claims,before_claims);self.assertFalse(self.c.privacy_attempted)
            finally:
                server.shutdown();server.server_close();thread.join(2);self.assertFalse(thread.is_alive());gateway.journal.close()
    def test_unrestored_owner_change_fails_cleanup_without_auto_mutation(self):
        self.owner.restored=False;r=self.call('closeCaseControls',case='QUEUE-01');self.assertFalse(r['allOwnedControlsClosed']);self.assertEqual(self.owner.calls,[])
    def test_operation_claim_precedes_owner_and_unknown_is_not_replayed(self):
        identity=self.v['runId']+':QUEUE-01:1'
        def unknown(*_args):raise TimeoutError('not retained')
        self.c.owner=SimpleNamespace(__call__=unknown)
        # A real callable is needed, avoiding an attribute-only double.
        self.c.owner=unknown
        with self.assertRaises(TimeoutError):self.call('changeAnchor',case='QUEUE-01',args={'action':'change'},identity=identity)
        self.assertIn(identity,self.claims)
        with self.assertRaises(AssertionError):self.call('changeAnchor',case='QUEUE-01',args={'action':'change'},identity=identity)
    def test_query_observation_retains_only_cursor_digest(self):
        self.c.after_native('GET',p.QUEUE,native=True,request_id='r',sequence=1,body=b'',query='ownership=mine&dates=all&limit=25&cursor=OPAQUE_PRIVATE_CURSOR',status=200,data=b'{}',intercept=None)
        self.assertNotIn('OPAQUE_PRIVATE_CURSOR',json.dumps(self.c.records));self.assertEqual(self.c.records[0]['queryObservation']['cursorSha256'],p.sha(b'OPAQUE_PRIVATE_CURSOR'))
    def test_owner_account_mutation_and_wrong_recipe_status_refused(self):
        for edit in (lambda v:v['ownerExactRoutes'].append('POST '+p.PRIVACY),lambda v:v['ownerRecipes'][0]['requests'][2].update(expectedStatuses=[500])):
            v=registration();edit(v)
            with self.assertRaises(AssertionError):p.validate_registration(v,source='a'*40,run=v['runId'],now=time.time())
class Loader(unittest.TestCase):
    def test_disabled_profile_never_reads_any_source(self):
        with patch.object(g,'runtime_source_bytes',side_effect=AssertionError('must not read'))as r:self.assertEqual(g.verified_v1_controls(Path('/none'),'r',{}),(None,None));r.assert_not_called()
    def test_unknown_profile_and_cloud_refuse_before_source_or_secret(self):
        for extra in ({'CASEOPS_MOBILE_V1_PROFILE':'unreviewed'},{'K_SERVICE':'cloud'}):
            env={'CASEOPS_MOBILE_V1_CONTROLS':'1','CASEOPS_ENV':'local','CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256':'a'*64,**extra}
            with patch.object(g,'runtime_source_bytes',side_effect=AssertionError('unexpected source'))as r:
                with self.assertRaises(AssertionError):g.verified_v1_controls(Path('/none'),'r',env)
                r.assert_not_called()
    def test_actual_loader_consumes_verified_profile_and_pinned_base_without_network(self):
        with tempfile.TemporaryDirectory()as raw:
            root=Path(raw).resolve();v=registration();authority=root/'authority.json';authority.write_text(json.dumps({'control_secret':'b'*64}));authority.chmod(0o600);v['authorityEvidence']={'path':str(authority),'sha256':hashlib.sha256(authority.read_bytes()).hexdigest(),'uid':os.getuid()}
            v['implementationSha256']=hashlib.sha256((HERE/'local-queue-privacy-controls.py').read_bytes()).hexdigest();registration_path=root/'registration.json';registration_path.write_text(json.dumps(v));registration_path.chmod(0o600)
            calls=[]
            class Http:
                def __init__(self,*_a,**_k):pass
                def __enter__(self):return self
                def __exit__(self,*_a):pass
                def stream(self,method,route,**kwargs):
                    calls.append((method,route));data=json.dumps({'release_sha':'a'*40,'revision':'api-rev'if route.endswith('/api/build')else'web-rev'}).encode()
                    class Response:
                        status_code=200;headers={}
                        def __enter__(self):return self
                        def __exit__(self,*_args):pass
                        def iter_raw(self):return iter((data,))
                    return Response()
            fake=ModuleType('httpx');fake.Client=Http
            env={'CASEOPS_ENV':'local','CASEOPS_RELEASE_SHA':'a'*40,'CASEOPS_MOBILE_V1_CONTROLS':'1','CASEOPS_MOBILE_V1_PROFILE':'queue-privacy-v1','CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256':v['implementationSha256'],'CASEOPS_MOBILE_V1_REGISTRATION':str(registration_path),'CASEOPS_MOBILE_V1_REGISTRATION_SHA256':hashlib.sha256(registration_path.read_bytes()).hexdigest()}
            with patch.dict(sys.modules,{'httpx':fake}):
                result,source=g.verified_v1_controls(root,v['runId'],env);self.assertEqual(source,v['implementationSha256']);self.assertEqual(len(calls),2);self.assertIsInstance(result.base,ModuleType);self.assertEqual(result.base.__file__,str(HERE/'local-v1-controls.py'));result.close()
if __name__=='__main__':unittest.main()
