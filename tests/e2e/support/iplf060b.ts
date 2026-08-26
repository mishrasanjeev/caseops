import { spawnSync } from "node:child_process";
import path from "node:path";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./env";
import { expectStatus } from "./iplf058b";

export const JUDGE_PASSWORD = "JudgeWorkflow2026!";

export type JudgeWorkflowFixture = {
  courtId: string;
  judgeId: string;
  emptyJudgeId: string;
  noCorpusJudgeId: string;
  reviewId: string;
  reviewAuthorityId: string;
  duplicateJudgeId: string;
  benchId: string;
};

export async function bootstrapJudgeTenant(api: APIRequestContext) {
  const slug = `judge-workflow-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const email = `owner-${slug}@example.com`;
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "IPLF 060B Judge Workflow LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Judge Mapping Curator",
      owner_email: email,
      owner_password: JUDGE_PASSWORD,
    },
  });
  await expectStatus(response, 200, "bootstrap judge-workflow tenant");
  return { ...(await response.json()), slug, email };
}

export async function signInJudgeTenant(
  page: Page,
  tenant: { slug: string; email: string },
) {
  const response = await page.request.post(`${apiBaseUrl}/api/auth/login`, {
    data: {
      company_slug: tenant.slug,
      email: tenant.email,
      password: JUDGE_PASSWORD,
    },
  });
  await expectStatus(response, 200, "judge-workflow sign-in");
  const session = await response.json();
  await page.goto("/");
  await page.evaluate(
    (context) => {
      window.localStorage.setItem("caseops.session.context", JSON.stringify(context));
    },
    {
      company: session.company,
      user: session.user,
      membership: session.membership,
      capabilities: session.capabilities,
    },
  );
  return session;
}

export function createJudgeWorkflowFixture(): JudgeWorkflowFixture {
  const python =
    process.env.CASEOPS_E2E_PYTHON?.trim() ||
    (process.platform === "win32"
      ? path.join(repoRoot, "apps", "api", ".venv", "Scripts", "python.exe")
      : path.join(repoRoot, "apps", "api", ".venv", "bin", "python"));
  const script = String.raw`
import json
from datetime import date
from uuid import uuid4
from caseops_api.db.models import AuthorityDocument, Bench, Court, Judge, JudgeAlias, JudgeDecisionIndex, JudgeMappingReview
from caseops_api.db.session import get_session_factory
from caseops_api.services.judge_aliases import normalise

s = get_session_factory()()
court = s.query(Court).filter_by(name='Delhi High Court').one()
run = uuid4().hex[:10]
judge = Judge(court_id=court.id, full_name=f'Justice IPLF 060B {run}', current_position='Puisne Judge', source_name='official_court', source_url='https://delhihighcourt.nic.in/web/Judges', source_reference=f'official-roster-{run}', is_active=True)
empty_judge = Judge(court_id=court.id, full_name=f'Justice Empty 060B {run}', source_name='official_court', source_url='https://delhihighcourt.nic.in/web/Judges', is_active=True)
duplicate = Judge(court_id=court.id, full_name=f'Justice Duplicate 060B {run}', source_name='official_court', source_url='https://delhihighcourt.nic.in/web/Judges', is_active=True)
no_corpus_court = Court(name=f'IPLF 060B No Corpus Court {run}', short_name=f'NC-{run[:4]}', forum_level='tribunal', jurisdiction='India', is_active=True)
s.add_all([judge, empty_judge, duplicate, no_corpus_court])
s.flush()
no_corpus_judge = Judge(court_id=no_corpus_court.id, full_name=f'Justice No Corpus 060B {run}', source_name='official_court', source_url='https://example.gov.in/judges/no-corpus', is_active=True)
s.add(no_corpus_judge)
s.add_all([
    JudgeAlias(judge_id=judge.id, alias_text=f'J. IPLF 060B {run}', alias_normalised=normalise(f'J. IPLF 060B {run}'), source='official_court', source_url='https://delhihighcourt.nic.in/web/Judges'),
    JudgeAlias(judge_id=duplicate.id, alias_text=f'J. Duplicate 060B {run}', alias_normalised=normalise(f'J. Duplicate 060B {run}'), source='official_court', source_url='https://delhihighcourt.nic.in/web/Judges'),
])
bench = Bench(court_id=court.id, name=f'IPLF 060B Division Bench {run}', source_name='official_court', source_url='https://delhihighcourt.nic.in/web/Judges')
s.add(bench)
for index in range(12):
    document = AuthorityDocument(source='delhi_high_court_recent_judgments', adapter_name='iplf-060b-playwright-v1', court_name=court.name, forum_level=court.forum_level, document_type='judgment', title=f'IPLF 060B mapped authority {index} {run}', case_reference=f'W.P.(C) {100 + index}/2026', bench_name='Raw bench evidence', neutral_citation=f'2026:DHC:{100 + index}', decision_date=date(2026, 8, min(index + 1, 28)), canonical_key=f'iplf-060b-e2e:{run}:{index}', source_reference=f'https://delhihighcourt.nic.in/judgments/{run}-{index}.pdf', summary='Source-backed judge workflow fixture.', judges_json=json.dumps([f'J. IPLF 060B {run}']), sections_cited_json=json.dumps(['Section 11 Arbitration Act']))
    s.add(document)
    s.flush()
    eligible = index != 0
    s.add(JudgeDecisionIndex(judge_id=judge.id, authority_document_id=document.id, role='sat_on', year=2026, matched_alias=f'J. IPLF 060B {run}', match_confidence='exact' if eligible else 'low', raw_judge_name=f'J. IPLF 060B {run}', source_ordinal=0, mapping_status='auto_confirmed' if eligible else 'needs_review', resolver_version='judge-alias-v2-e2e', evidence_json={'source': 'judges_json', 'ordinal': 0}, is_analytics_eligible=eligible))
review_document = AuthorityDocument(source='delhi_high_court_recent_judgments', adapter_name='iplf-060b-playwright-v1', court_name=court.name, forum_level=court.forum_level, document_type='judgment', title=f'IPLF 060B collision authority {run}', decision_date=date(2026, 8, 20), canonical_key=f'iplf-060b-review:{run}', source_reference=f'https://delhihighcourt.nic.in/judgments/{run}-review.pdf', summary='Collision evidence fixture.', judges_json=json.dumps([f'Justice IPLF 060B {run}']))
s.add(review_document)
s.flush()
review = JudgeMappingReview(authority_document_id=review_document.id, court_id=court.id, raw_judge_name=f'Justice IPLF 060B {run}', raw_judge_name_normalised=normalise(f'Justice IPLF 060B {run}'), source_ordinal=0, reason='collision', candidate_judge_ids_json=[judge.id], status='open', resolver_version='judge-alias-v2-e2e')
s.add(review)
s.commit()
print(json.dumps({'courtId': court.id, 'judgeId': judge.id, 'emptyJudgeId': empty_judge.id, 'noCorpusJudgeId': no_corpus_judge.id, 'reviewId': review.id, 'reviewAuthorityId': review_document.id, 'duplicateJudgeId': duplicate.id, 'benchId': bench.id}))
s.close()
`;
  const result = spawnSync(python, ["-c", script], {
    cwd: repoRoot,
    encoding: "utf8",
    env: {
      ...process.env,
      ...e2eEnv,
      PYTHONPATH: [path.join(repoRoot, "apps", "api", "src"), process.env.PYTHONPATH]
        .filter(Boolean)
        .join(path.delimiter),
    },
  });
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
  const line = result.stdout
    .trim()
    .split(/\r?\n/)
    .reverse()
    .find((value) => value.trim().startsWith("{"));
  expect(line, result.stdout).toBeTruthy();
  return JSON.parse(line!) as JudgeWorkflowFixture;
}
