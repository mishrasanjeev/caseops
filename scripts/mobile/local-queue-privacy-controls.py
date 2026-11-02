"""Separate disabled-default two-case controls. Never an account mutation API.

The gateway passes the descriptor-verified compiled legacy helpers explicitly.
This file never imports a hyphenated sibling by pathname.
"""
import hashlib
import hmac
import json
from pathlib import Path
import re
import threading
import time

PROFILE = "queue-privacy-v1"
BASE_SHA256 = "a03af49be43afd3618688c64e0f7ac7938b8fa3e5e30b05bff00aeeb629ec4fc"
CASES = {"QUEUE-01": 24, "PRIVACY-01": 24}
CAPABILITIES = ("readQueue", "readOwnPrivacy", "changeAnchor", "armPrivacyAckLoss",
                "readControlReceipt", "readNativeRequest", "closeCaseControls", "closeRunControls")
PRIVACY = "/api/account/deletion-requests"
QUEUE = "/api/matter-work-queue"
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
LIMITS = {"operations": 49, "caseOperations": 24, "http": 64, "lifetime": 480,
          "argumentBytes": 16384, "responseBytes": 1048576, "records": 100, "knownIds": 96}
def canonical(value):return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def receipt(value):
    assert set(value) == {"id", "operation_id", "request_type", "status", "requested_at", "deletion_completed"}
    assert UUID.fullmatch(value["id"]) and UUID.fullmatch(value["operation_id"])
    assert value["operation_id"] != "00000000-0000-0000-0000-000000000000"
    assert value["request_type"] == "account_deletion" and value["status"] == "received" and value["deletion_completed"] is False
    from datetime import datetime
    stamp = datetime.fromisoformat(value["requested_at"].replace("Z", "+00:00"))
    assert stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0
    return value
def validate_registration(v, *, source, run, now):
    assert v["kind"] == "registered-queue-privacy-controls" and v["profile"] == PROFILE and type(v["schemaVersion"]) is int and v["schemaVersion"] == 1
    assert v["observed"] is True and v["readyForLive"] is True and v["preparedOnly"] is False
    assert v["environment"] == "docker-integration" and v["syntheticDataOnly"] is True and v["noPaidMarker"] == "no-paid-providers"
    assert v["directDatabaseWrites"] is False and v["nativeMutationsForwardedByControls"] is False
    assert v["sourceSha"] == source and v["runId"] == run and 0 < v["expiresAt"]-now <= LIMITS["lifetime"]
    assert v["baseImplementationSha256"] == BASE_SHA256 and tuple(v["capabilities"]) == CAPABILITIES and v["caseControlLimits"] == CASES
    assert UUID.fullmatch(v["companyId"]) and re.fullmatch(r"[a-f0-9]{16,64}", v["registrationId"])
    ids=v["syntheticIds"];assert 0 < len(ids) <= 92 and len(set(ids)) == len(ids) and all(UUID.fullmatch(x) for x in ids)
    assert set(v["actors"]) == {"owner", "member", "second-company"}
    for a in v["actors"].values():
        assert all(UUID.fullmatch(a[k]) for k in ("companyId", "membershipId", "userId"))
        assert all(a[k] in ids for k in ("companyId", "membershipId", "userId")), "QP_COMPLETE_ACTOR_CONTROL_IDENTITIES_REQUIRED"
        assert set(a["credentialEvidence"]) == {"path", "sha256", "uid"} and re.fullmatch(r"[a-f0-9]{64}", a["credentialEvidence"]["sha256"])
        assert type(a["credentialEvidence"]["uid"]) is int and a["credentialEvidence"]["uid"] >= 0
        assert isinstance(a["credentialEvidence"]["path"],str) and Path(a["credentialEvidence"]["path"]).is_absolute()
    assert set(v["authorityEvidence"]) == {"path","sha256","uid"} and type(v["authorityEvidence"]["uid"]) is int and v["authorityEvidence"]["uid"] >= 0
    assert isinstance(v["authorityEvidence"]["path"],str) and Path(v["authorityEvidence"]["path"]).is_absolute()
    assert re.fullmatch(r"[a-f0-9]{64}",v["authorityEvidence"]["sha256"])
    assert v["actors"]["owner"]["companyId"] == v["actors"]["member"]["companyId"] == v["companyId"]
    assert v["actors"]["second-company"]["companyId"] != v["companyId"]
    assert len({a["userId"] for a in v["actors"].values()}) == 3
    assert len({a["membershipId"] for a in v["actors"].values()}) == 3
    anchor=v["anchor"];assert anchor["id"] in ids and anchor["matterId"] in ids
    expected={"GET "+QUEUE,"GET "+PRIVACY,"POST "+PRIVACY,"GET /api/matters/"+anchor["matterId"]+"/workspace"}
    assert set(v["exactRoutes"]) == expected and len(v["exactRoutes"]) == len(expected)
    allowed={"GET /api/matters/"+anchor["matterId"],"GET /api/matters/"+anchor["matterId"]+"/tasks",
             "PATCH /api/matters/"+anchor["matterId"]+"/tasks/"+anchor["id"]}
    assert set(v["ownerExactRoutes"]) == allowed and len(v["ownerExactRoutes"]) == 3
    assert len(v["ownerRecipes"]) == 2 and {r["argumentsSha256"] for r in v["ownerRecipes"]} == {sha(canonical({"action":"change"})),sha(canonical({"action":"restore"}))}
    for r in v["ownerRecipes"]:
        assert r["caseId"] == "QUEUE-01" and r["capability"] == "changeAnchor" and len(r["requests"]) == 3
        assert [x["method"] for x in r["requests"]] == ["GET","GET","PATCH"]
        assert {x["method"]+" "+x["route"] for x in r["requests"]} == allowed
        assert set(r["requests"][2]["body"]) == {"due_on","expected_lifecycle_version","expected_updated_at"}
        assert all(x["expectedStatuses"] == [200] for x in r["requests"])
    return v

class Controls:
    def __init__(self, registration, registration_sha, authority, *, base, owner, persist=lambda row:None, claim=lambda key:None,
                 close_journal=lambda:None, principal=None, http_count=lambda:0, now=time.time):
        self.registration,self.registration_sha,self.authority=registration,registration_sha,authority
        self.base,self.owner,self.persist,self.claim,self.close_journal,self.principal,self.now=base,owner,persist,claim,close_journal,principal,now
        self.http_count=http_count
        self.closed=False;self.operations=set();self.counts={};self.records=[];self.arms={};self.known_ids=set(registration["syntheticIds"])
        self.lock=threading.RLock();self.dispatch_lock=threading.Lock();self.privacy_attempted=False;self.privacy_admitted=False;self.final_cleanup=False
    def live(self):assert not self.closed and self.now()<self.registration["expiresAt"],"QP_CLOSED_OR_EXPIRED"
    def route(self,method,route):assert method+" "+route in self.registration["exactRoutes"],"QP_EXACT_ROUTE_REQUIRED"
    def handle(self,raw,*,marker,authority):
        assert marker=="no-paid-providers" and hmac.compare_digest(authority,self.authority)
        assert self.dispatch_lock.acquire(blocking=False),"QP_SERIAL_CONTROL_REQUIRED"
        try:return self._handle(raw)
        finally:self.dispatch_lock.release()
    def _handle(self,raw):
        self.live();assert isinstance(raw,bytes) and len(raw)<=LIMITS["argumentBytes"]
        q=json.loads(raw);assert set(q)=={"schemaVersion","capability","caseId","operationId","runId","registrationSha256","args"}
        cap,case,args=q["capability"],q["caseId"],q["args"]
        assert q["schemaVersion"]==1 and type(q["schemaVersion"])is int and cap in CAPABILITIES and case in CASES
        assert q["runId"]==self.registration["runId"] and q["registrationSha256"]==self.registration_sha
        assert cap in ({"readQueue","changeAnchor","readNativeRequest","closeCaseControls"} if case=="QUEUE-01" else
                       {"readOwnPrivacy","armPrivacyAckLoss","readControlReceipt","readNativeRequest","closeCaseControls","closeRunControls"}),"QP_EXACT_CASE_CAPABILITY_REQUIRED"
        assert isinstance(args,dict) and not re.search(r'"(?:password|secret|token|authorization|cookie)"\s*:',json.dumps(args),re.I)
        assert re.fullmatch(re.escape(q["runId"]+":"+case+":")+r"[1-9][0-9]{0,3}",q["operationId"])
        assert q["operationId"] not in self.operations and len(self.operations)<49
        if cap=="closeRunControls":assert case=="PRIVACY-01" and not self.final_cleanup;self.final_cleanup=True
        else:assert self.counts.get(case,0)<24
        self.claim(q["operationId"]);self.operations.add(q["operationId"]);self.counts[case]=self.counts.get(case,0)+1
        self.persist({"type":"qp_control_started","operationId":q["operationId"],"capability":cap,"caseId":case})
        if cap=="armPrivacyAckLoss":
            assert case=="PRIVACY-01" and args=={} and not self.arms and not self.privacy_attempted
            identity=sha(q["operationId"].encode())[:32];self.arms[identity]={"id":identity,"caseId":case,"consumed":False,"requestsForwarded":0,"upstreamAcknowledged":False,"closed":False};facts={"id":identity}
        elif cap=="readControlReceipt":
            assert set(args)=={"id"} and args["id"] in self.arms;facts=dict(self.arms[args["id"]]);assert facts["caseId"]==case
        elif cap=="readNativeRequest":
            assert set(args)=={"method","route","afterSequence"} and type(args["afterSequence"])is int and args["afterSequence"]>=0
            self.route(args["method"],args["route"]);facts={"requests":[r for r in self.records if r["sequence"]>args["afterSequence"] and r["method"]==args["method"] and r["route"]==args["route"]]}
        elif cap=="closeCaseControls":
            assert args=={}
            for arm in self.arms.values():
                if arm["caseId"]==case:arm["closed"]=True
            facts={"allOwnedControlsClosed":self.owner.restoration_complete()}
        elif cap=="closeRunControls":
            assert args=={};facts={"allOwnedControlsClosed":self.owner.restoration_complete(),"authorityCleared":True,"journalClosed":True}
        else:
            assert (cap=="changeAnchor" and case=="QUEUE-01") or cap in ("readQueue","readOwnPrivacy")
            facts=self.owner(cap,case,args)
        result={"observed":True,"sourceSha":self.registration["sourceSha"],"runId":q["runId"],"caseId":case,"capability":cap,
                "operationId":q["operationId"],"noPaidMarker":"no-paid-providers","directDatabaseWrites":False,"nativeMutationsForwardedByControls":False,"httpRequestsCharged":self.http_count(),**facts}
        assert len(canonical(result))<=LIMITS["responseBytes"]
        self.persist({"type":"qp_control_completed","operationId":q["operationId"],"caseId":case,"capability":cap})
        if cap=="closeRunControls":self.close()
        return result
    def validate_native_request(self,method,route,*,native,body,query,authorization=None,cookie_present=False):
        if method!="POST" or route!=PRIVACY:return
        assert native and cookie_present is False and isinstance(authorization,str) and authorization.startswith("Bearer cnat_"),"QP_NATIVE_NO_COOKIE_AUTHORITY_REQUIRED"
        self.live();assert isinstance(body,bytes) and len(body)<=4096;value=json.loads(body);assert set(value)=={"operation_id","confirmation"} and value["confirmation"]=="request_account_deletion"
        assert UUID.fullmatch(value["operation_id"]) and int(value["operation_id"].replace("-",""),16)>0
        assert not self.privacy_attempted and len(self.arms)==1,"QP_PRIVACY_POST_REPLAY_REFUSED"
        self.claim("native:privacy-one-post");self.privacy_attempted=True
        assert callable(self.principal),"QP_ACTUAL_NATIVE_PRINCIPAL_REQUIRED"
        actual=self.principal(authorization);expected=self.registration["actors"]["member"]
        assert actual=={k:expected[k] for k in ("userId","membershipId","companyId")},"QP_NATIVE_SELF_REQUIRED"
        self.operation_id=value["operation_id"];self.privacy_admitted=True
    def before_native(self,method,route,*,native,request_id):
        if not native or method!="POST" or route!=PRIVACY:return None
        assert self.privacy_attempted and self.privacy_admitted
        arm=next(iter(self.arms.values()));assert not arm["consumed"] and not arm["closed"]
        arm.update(consumed=True,requestsForwarded=1,requestId=request_id);return {"arm":arm}
    def after_native(self,method,route,*,native,request_id,sequence,body,query,status,data,intercept):
        if not native or method+" "+route not in self.registration["exactRoutes"]:return False
        assert len(self.records)<100
        row={"sequence":sequence,"method":method,"route":route,"status":status,"requestId":request_id}
        if route==QUEUE:
            from urllib.parse import parse_qs
            q=parse_qs(query,strict_parsing=True);assert set(q)<={"ownership","dates","limit","cursor"} and all(len(v)==1 for v in q.values())
            assert q.get("ownership",["mine"])[0] in ("mine","team","unassigned") and q.get("dates",["all"])[0]in("all","dated","undated") and q.get("limit",["25"])[0]=="25"
            assert "cursor"not in q or len(q["cursor"][0])<=4000
            row["queryObservation"]={"ownership":q.get("ownership",["mine"])[0],"dates":q.get("dates",["all"])[0],"cursorSha256":sha(q["cursor"][0].encode())if"cursor"in q else None}
        if method=="POST":
            assert route==PRIVACY and self.privacy_attempted
            row["bodyObservation"]={"keys":["confirmation","operation_id"],"canonicalSha256":sha(canonical(json.loads(body)))}
            if status==202:
                value=receipt(json.loads(data));assert value["operation_id"]==self.operation_id
                assert len(self.known_ids|{value["id"],value["operation_id"]})<=96
                row["responseObservation"]=value
                assert intercept and intercept["arm"]["requestId"]==request_id
        # The original upstream ACK must be fsynced before intentional client
        # response loss is permitted. A failed journal leaves the attempt
        # consumed and the ACK unknown; it can never authorize replay or loss.
        self.persist({"type":"qp_native_request_observed",**row})
        self.records.append(row)
        if method=="POST" and status==202:
            self.known_ids.update((value["id"],value["operation_id"]))
            intercept["arm"].update(upstreamAcknowledged=True,upstreamStatus=202,responseObservation=value,durableAck=True)
        return self.should_withhold(intercept,status)
    @staticmethod
    def should_withhold(intercept,status):return bool(intercept and status==202 and intercept["arm"].get("upstreamAcknowledged") is True and intercept["arm"].get("durableAck") is True)
    def close(self):
        if not self.closed:
            self.closed=True
            try:self.owner.close()
            finally:self.authority=None;self.close_journal()

def from_environment(root,run_id,*,environment=None,verified_implementation_sha256=None,verified_registration_bytes=None,base_module=None,**_unused):
    env=environment or {};assert env.get("CASEOPS_ENV")=="local" and env.get("CASEOPS_MOBILE_V1_CONTROLS")=="1"
    assert not any(env.get(k)for k in("K_SERVICE","K_REVISION","CLOUD_RUN_JOB","GAE_ENV","FUNCTION_TARGET"))
    assert base_module is not None and env.get("CASEOPS_MOBILE_V1_PROFILE")==PROFILE,"QP_VERIFIED_BASE_REQUIRED"
    v=json.loads(verified_registration_bytes);assert sha(verified_registration_bytes)==env["CASEOPS_MOBILE_V1_REGISTRATION_SHA256"]
    validate_registration(v,source=env["CASEOPS_RELEASE_SHA"],run=run_id,now=time.time())
    assert v["implementationSha256"]==verified_implementation_sha256
    # This is a private copy of the descriptor-compiled helper module, never the
    # ordinary old17 module. Charge every authentication/admission/owner HTTP call.
    calls={"count":0};original=base_module.bounded_http
    def charged(*args,**kwargs):
        calls["count"]+=1;assert calls["count"]<=64,"QP_ALL_HTTP_BOUND";return original(*args,**kwargs)
    base_module.bounded_http=charged
    import httpx
    with httpx.Client(timeout=3,follow_redirects=False,headers={"X-CaseOps-Automated-Test":"no-paid-providers"})as http:
        for origin,route,key in(("http://api:8000","/api/build","backendRevision"),("http://web:3000","/api/release-identity","webRevision")):
            r=charged(http,"GET",origin+route);assert r.status_code==200 and r.json()["release_sha"]==v["sourceSha"] and r.json()["revision"]==v[key]
    authority=base_module.checked_json(v["authorityEvidence"],root,private=True)["control_secret"];assert re.fullmatch(r"[a-f0-9]{64}",authority)
    class Owner(base_module.RegisteredOwner):
        def __call__(self,cap,case,args):
            if cap=="changeAnchor":return super().__call__(cap,case,args)
            actor=args.get("actor","member");assert actor in("member","second-company")
            if cap=="readQueue":
                assert case=="QUEUE-01" and actor=="member" and set(args)<={"ownership","dates","cursor"}
                from urllib.parse import urlencode
                assert args["ownership"]in("mine","team","unassigned")and args["dates"]in("all","dated","undated")
                p={"ownership":args["ownership"],"dates":args["dates"],"limit":25}
                if args.get("cursor")is not None:assert isinstance(args["cursor"],str)and 0<len(args["cursor"])<=4000;p["cursor"]=args["cursor"]
                route=QUEUE+"?"+urlencode(p)
            else:assert cap=="readOwnPrivacy" and set(args)<={"actor"};route=PRIVACY
            r=charged(self.client(actor),"GET",route);assert r.status_code==200;value=r.json()
            if cap=="readOwnPrivacy":
                assert set(value)=={"request"}
                if value["request"]is not None:receipt(value["request"])
            else:
                assert value["scope"]=="matter_tasks" and len(value["items"])<=25
                assert all(x["id"]in v["syntheticIds"] and x["matter"]["id"]in v["syntheticIds"]for x in value["items"])
            return {"status":200,"value":value}
        def close_case(self,case):return {"allOwnedControlsClosed":self.restoration_complete()}
    owner=Owner(v,root)
    def principal(authorization):
        assert isinstance(authorization,str)and authorization.startswith("Bearer cnat_")
        with httpx.Client(base_url="http://api:8000",timeout=3,follow_redirects=False,headers={"Authorization":authorization,"X-CaseOps-Automated-Test":"no-paid-providers"})as h:
            r=charged(h,"GET","/api/auth/me");assert r.status_code==200;value=r.json()
            return {"userId":value["user"]["id"],"membershipId":value["membership"]["id"],"companyId":value["company"]["id"]}
    persist,close=base_module.create_journal(root,v["registrationId"])
    def claim(identity):
        with (root/("qp-attempt-"+sha(identity.encode())+".json")).open("x",encoding="utf-8")as f:f.write(json.dumps({"identitySha256":sha(identity.encode()),"noReplay":True}))
    try:
        owner.claim=claim
        return Controls(v,sha(verified_registration_bytes),authority,base=base_module,owner=owner,persist=persist,claim=claim,close_journal=close,principal=principal,http_count=lambda:calls["count"])
    except BaseException as error:
        try:owner.close()
        except BaseException:error.add_note("QP_OWNER_CLEANUP_UNVERIFIED_DURING_SETUP")
        try:close()
        except BaseException:error.add_note("QP_JOURNAL_CLEANUP_UNVERIFIED_DURING_SETUP")
        raise
