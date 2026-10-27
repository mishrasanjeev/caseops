"""Independent exact two-case inventory and source-closure contracts only."""
from pathlib import Path
import ast,json,re,unittest
ROOT=Path(__file__).resolve().parents[2]
CASES=("QUEUE-01","PRIVACY-01")
class Inventory(unittest.TestCase):
    def test_literal_independent_cases_and_all_executable_bodies(self):
        contract=(ROOT/'apps/mobile/e2e/queue-privacy-contract.mjs').read_text();source=(ROOT/'apps/mobile/e2e/queue-privacy.mjs').read_text()
        self.assertIn("cases:Object.freeze(['QUEUE-01','PRIVACY-01'])",contract)
        self.assertEqual(tuple(re.findall(r"\{id:'((?:QUEUE|PRIVACY)-01)',run:async",source)),CASES)
        self.assertIn('phases:6,sessions:2',contract)
    def test_49_rpc_profile_has_independent_per_case_literals_and_fixed_call_envelope(self):
        source=(ROOT/'scripts/mobile/local-queue-privacy-controls.py').read_text();tree=ast.parse(source)
        values={n.targets[0].id:ast.literal_eval(n.value)for n in tree.body if isinstance(n,ast.Assign)and isinstance(n.targets[0],ast.Name)and n.targets[0].id in('CASES','LIMITS')}
        self.assertEqual(values['CASES'],{'QUEUE-01':24,'PRIVACY-01':24});self.assertEqual(sum(values['CASES'].values())+1,49);self.assertEqual(values['LIMITS']['operations'],49)
        contract=(ROOT/'apps/mobile/e2e/queue-privacy-contract.mjs').read_text();self.assertIn('18+17+QP_CALL_INVENTORY.finalCleanup<=49',contract)
        source=(ROOT/'apps/mobile/e2e/queue-privacy.mjs').read_text();self.assertIn('attempt<4',source);self.assertEqual(source.count('await completedNativeRead('),2)
    def test_original_three_inventories_and_17_control_caps_are_unchanged(self):
        c=json.loads((ROOT/'apps/mobile/e2e/core-20261025.json').read_text());self.assertEqual(len(c['cases']),23)
        old=(ROOT/'apps/mobile/e2e/v1-workflows-inventory.mjs').read_text();self.assertEqual(len(re.findall(r"\['(?:SOURCE|WORK|COUNSEL|INBOX)-\d{2}',",old)),17);self.assertIn('<= 264',old)
        self.assertIn('native-ios-files-2026-10-26',(ROOT/'apps/mobile/e2e/ios-files.mjs').read_text())
    def test_no_filter_retry_install_or_owner_account_mutation_entry(self):
        source=(ROOT/'scripts/mobile/run-queue-privacy.mjs').read_text();self.assertNotIn('--case',source);self.assertNotIn('--grep',source);self.assertIn('connectionRetryCount:0',source)
        self.assertIn('install: false',(ROOT/'scripts/mobile/run-v1-workflows.mjs').read_text());self.assertIn('for(const scenario of queuePrivacyScenarios)',source)
        controls=(ROOT/'scripts/mobile/local-queue-privacy-controls.py').read_text();self.assertIn('ownerExactRoutes',controls);self.assertIn('QP_NATIVE_SELF_REQUIRED',controls);self.assertIn('status==202',controls)
    def test_actual_pinned_base_source_and_lf_are_exact(self):
        import hashlib
        base=(ROOT/'scripts/mobile/local-v1-controls.py').read_bytes();sha=hashlib.sha256(base).hexdigest();self.assertNotIn(b'\r',base)
        for name in('scripts/mobile/local-gateway.py','scripts/mobile/local-queue-privacy-controls.py','apps/mobile/e2e/queue-privacy-contract.mjs'):self.assertIn(sha,(ROOT/name).read_text())
    def test_every_control_profile_source_has_context_and_ci_lf_contract(self):
        attributes=(ROOT/'.gitattributes').read_text();workflow=(ROOT/'.github/workflows/mobile-source.yml').read_text();compose=(ROOT/'compose.mobile-local.yml').read_text()
        for name in('scripts/mobile/local-queue-privacy-controls.py','scripts/mobile/local-queue-privacy-controls.test.py','scripts/mobile/queue-privacy.test.py'):
            self.assertIn(name+' text eol=lf',attributes)
        self.assertIn('python3 scripts/mobile/local-queue-privacy-controls.test.py',workflow);self.assertIn('python3 scripts/mobile/queue-privacy.test.py',workflow)
        self.assertIn('CASEOPS_MOBILE_V1_PROFILE:',compose);self.assertIn('./scripts/mobile:/mobile-fixture:ro',compose)
    def test_complete_producer_admission_and_native_controls_are_not_free_metadata_calls(self):
        source=(ROOT/'apps/mobile/e2e/queue-privacy-fixture.mjs').read_text();self.assertIn('requests:74,posts:53,patches:1',source);self.assertIn("admissions,12",source);self.assertIn("requests,74",source);self.assertIn("posts,53",source)
        runner=(ROOT/'scripts/mobile/run-queue-privacy.mjs').read_text();self.assertLess(runner.index("io.getJson(isolation.gatewayUrl+'/api/build')"),runner.index('const loaded=io.reader('));self.assertLess(runner.index("io.getJson(isolation.webGatewayUrl+'/api/release-identity')"),runner.index('const loaded=io.reader('))
    def test_private_templates_remain_pending_and_named_identity_hooks_exist(self):
        source=(ROOT/'scripts/mobile/prepare-queue-privacy-fixture.mjs').read_text();self.assertIn('observed:false,readyForLive:false,preparedOnly:true',source)
        source=(ROOT/'apps/mobile/src/application/screens/WorkScreen.tsx').read_text()
        for name in('queue-task-title','queue-task-matter','queue-task-id','queue-task-status','queue-task-priority','queue-task-due','queue-task-created','queue-task-updated','queue-task-lifecycle','queue-back'):self.assertEqual(source.count('testID="'+name+'"'),1)
if __name__=='__main__':unittest.main()
