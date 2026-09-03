# PRD: Litigation Intelligence Expansion

Status: Approved addendum; LI-S1 through LI-S13 implemented/ready at their scoped V1/foundation boundaries
Date: 2026-05-11
Source input: `C:\Users\mishr\Downloads\CaseOps.pdf`
Canonical PRD anchor: `docs/PRD_CODEX_2026-04-23.md`
Related addenda:
- `docs/PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05.md`
- `docs/PRD_BENCH_MAPPING_2026-04-25.md`
- `docs/PRD_BENCH_STRATEGY_2026-04-26.md`
- `docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md`

This addendum began as a planning document. Current repo truth as of
2026-05-12: LI-S1, LI-S2, LI-S3, LI-S4 foundation, LI-S5, LI-S6 integration
review, LI-S7A/B/C product slices, LI-S8 PRD/status alignment, LI-S9 review
mutations, LI-S10 calibrated predictive expansion, LI-S11 legal knowledge graph
materialization foundation, LI-S12 safe source-expansion readiness/proof
tooling, and LI-S13 transcript-first hearing coach foundation are implemented
at their defined scopes. Remaining caveats are not abandoned: broad
district/session/tribunal ingestion beyond the LI-S12 proof layer remains
deferred until lawful adapters and quality proof exist.

## 1. Purpose

The attached PDF asks CaseOps to expand from matter management plus legal
research into a deeper litigation intelligence operating system for Indian
lawyers. The useful product direction is real: proceeding-sheet absorption,
affidavit-based hearing preparation, district and tribunal source coverage,
bench/forum context, and a legal knowledge graph.

Several PDF asks are predictive and must be implemented carefully as explicit
closure slices. CaseOps must not ship opaque or unsupported "black-box"
predictions. It may ship controlled predictive intelligence only when the
surface is explainable, source-backed, tenant-policy gated, audited, and
reviewable by a lawyer.

Allowed controlled predictive surfaces include judge/bench/forum outcome
tendency, interim relief likelihood, notice issuance likelihood, adjournment
likelihood, stay/interim order frequency, disposal or delay risk, matter risk,
settlement inclination signal, and mock-hearing performance scoring. Each
surface must show sample size, confidence band, supporting judgment/order IDs,
feature explanation, limitation note, human-review gate, tenant AI policy gate,
audit trail, and the label "decision support, not legal advice."

If the evidence is weak, the output must degrade to `insufficient_evidence`.
Predictions must never be based only on LLM intuition. Emotional or
psychological scoring must be framed as observable hearing-preparation
performance metrics, not as medical, mental-health, biometric, or personality
diagnosis.

## 2. PRD Mapping

Affected canonical journeys:

| Journey | Why affected |
| --- | --- |
| J03 Daily matter workspace | Proceeding sheets, compliance directions, timeline, tasks, and matter cockpit surfaces. |
| J03A Case summary and matter brief generation | Proceeding-sheet summaries and hearing-prep briefs reuse summary/export foundations. |
| J04 Document intake, OCR, viewing, and annotation | Affidavits, proceeding sheets, tribunal orders, and district orders are document-first workflows. |
| J05 Research and authority discovery | District, tribunal, and lower-court source coverage expands public-law retrieval. |
| J06 Court, judge, bench, and tribunal intelligence | Bench/forum intelligence must remain evidence-backed and tribunal-aware. |
| J07 Drafting studio and templates | Affidavit prep, cross-examination prep packs, and simulator outputs may feed drafts. |
| J08 Hearings, calendar, tasks, and notifications | Proceeding-sheet directions become deadlines, hearing updates, and reminders. |
| J09 Recommendations and legal strategy | Next-action recommendations must be source-grounded and lawyer-reviewed. |
| J15 Data platform and enterprise deployment | New public-source ingestion must preserve source lineage, Voyage quality gates, and reranking. |

Affected module IDs:

| Module | Current direction |
| --- | --- |
| M03 Documents, OCR, viewer, annotations | Extend for affidavit/proceeding-sheet classifiers and source-linked extraction. |
| M04 Research and authority retrieval | Extend to district/session courts and tribunals only after source policy and quality gates. |
| M05 Court, judge, bench, tribunal intelligence | Add controlled predictive intelligence with source lineage, confidence bands, feature explanation, policy gates, and human review. |
| M06 Drafting studio and templates | Reuse affidavit and counter-affidavit templates; add hearing-prep artifacts. |
| M07 Recommendations and strategy | Add next-action and evidence-gap recommendations with human review. |
| M08 Hearings, calendar, tasks, notifications | Proceeding sheets become deadlines, tasks, and timeline events. |
| M15 Data platform and enterprise deployment | Source registry, ingestion lineage, vector quality, and audit. |
| M16 Matter summary and case brief generation | Proceeding and hearing-prep summaries. |
| New MOD-LI-001 | Litigation Intelligence Expansion umbrella module for this PRD. |

## 3. Full PDF Requirement Extraction

The PDF is 16 pages. Section 2, Bench Intelligence and Judicial Analytics, is
duplicated across pages 4 through 7; it is extracted once below.

### 3.1 Overview

The PDF identifies gaps across:

- Litigation hearing preparation.
- AI-assisted client training.
- Bench and judge behavior analytics.
- Tribunal and district court coverage.
- Daily proceeding sheet ingestion.
- End-to-end litigation intelligence workspace.

CaseOps interpretation:

- Build the useful workflows as matter-native legal operations.
- Keep data in source systems and retrieval, not model memory.
- Require source lineage, citations, review state, and limitations.
- Allow predictive and scoring labels only when they are explicitly statistical,
  source-backed, explainable, and labelled as decision support rather than
  legal advice.

### 3.2 Chief Affidavit Based Hearing Preparation

PDF problem:

- Opposite counsel frames questions and cross-examination from chief affidavits.
- Lawyers prepare clients manually.
- No centralized AI-driven system exists to analyze affidavit content, predict
  probable questions, train clients, or simulate courtroom questioning.

PDF proposed module:

- Upload and parse chief affidavits.
- Extract facts, claims, contradictions, dates, financial figures, and
  names/entities.
- Generate possible cross-examination questions, weakness indicators,
  contradiction alerts, risk analysis.
- Create mock hearing simulations for client preparation.

PDF Affidavit Analyzer capabilities:

- OCR and PDF parsing.
- Section-wise extraction.
- Timeline generation.
- Key statement extraction.
- Contradiction detection.

PDF AI outputs:

- Potential challenge areas.
- Statements requiring evidence.
- Risky admissions.
- Missing supporting documents.

PDF Cross-Examination Question Generator:

- Generate fact-based questions.
- Timeline inconsistency questions.
- Financial scrutiny questions.
- Intent or motive questions.
- Evidence contradiction questions.
- Example questions tied to page references and annexures.

PDF Client Hearing Training Simulator:

- Mock courtroom mode.
- Voice-enabled AI questioning.
- Timed responses.
- Stress simulation.
- Performance scoring.
- Confidence score.
- Consistency score.
- Contradiction probability.
- Emotional instability detection.
- Response delay analysis.

CaseOps-compliant interpretation:

- "Risk analysis" may include matter-risk signals only when they are derived
  from observable matter facts, cited source material, and disclosed features.
- "Probable questions" becomes plausible cross-examination questions grounded
  in the affidavit and attached exhibits.
- "Performance scoring" becomes a preparation rubric with reviewer notes,
  observable metrics, source support, response consistency, and timing where
  the session records it.
- "Emotional instability detection" must not be framed as a mental-health or
  personality claim. In product terms it becomes observable hearing-prep
  metrics such as hesitations, changed answers, unsupported new facts, and
  delayed responses, with lawyer review.
- Voice and stress simulation are deferred; text-first V1 avoids client safety,
  consent, storage, and accessibility complexity.

### 3.3 Technical Architecture Suggested by PDF

PDF AI components:

- NLP-based affidavit parser.
- Legal entity extraction model.
- Retrieval-Augmented Generation.
- LLM-based question generation.
- Vector database for legal context search.

PDF suggested stack:

- OCR: Tesseract or AWS Textract.
- NLP: spaCy or Legal-BERT.
- LLM: GPT, Claude, or open-source legal models.
- Vector DB: Pinecone or Weaviate.
- Speech: Whisper or Azure Speech.

CaseOps architecture decision:

- Reuse existing CaseOps document processing, OCR, LLM provider abstraction,
  ModelRun audit, Postgres/pgvector, Voyage `voyage-4-large`, reranking, and
  tenant AI policy.
- Do not add Pinecone or Weaviate while Postgres/pgvector is the existing
  production path.
- Speech is deferred until a privacy, consent, recording retention, and provider
  policy is approved.

### 3.4 Data Sources Suggested for Affidavit and Hearing Prep

PDF sources:

- Indian Kanoon.
- eCourts Services.
- Supreme Court of India.
- Delhi High Court Judgments.

CaseOps source policy:

- Official Supreme Court and High Court sources are allowed when terms and
  source lineage are recorded.
- Indian Kanoon is not a default source unless licensing and terms are approved.
- eCourts access must be verified. Do not assume public API access or bypass
  captcha/session gates.

### 3.5 Bench Intelligence and Judicial Analytics

PDF problem:

- Lawyers want strategic intelligence regarding judge behavior, court
  aggressiveness, likely questioning patterns, interim-order tendencies, and
  average disposal timelines.
- This knowledge currently exists through experience and informal networks.

PDF proposed engine:

- Judge and bench analytics.

PDF Judge/Bench Profile data points:

- Historical judgments.
- Bail approval ratio.
- Stay order frequency.
- Interim relief patterns.
- Adjournment tendencies.
- Strictness/aggressiveness score.

PDF Courtroom Behaviour Analytics:

- "Bench asks detailed factual questions."
- "Strict on procedural delays."
- "Favors documentary evidence."
- "High scrutiny in arbitration matters."

PDF Outcome Prediction:

- Probability of interim relief.
- Probability of adjournment.
- Probability of notice issuance.
- Settlement inclination score.

PDF suggested AI models:

- Judgment summarization.
- Outcome classification.
- Judicial behavior clustering.
- Legal trend analytics.

PDF suggested sources:

- Supreme Court Cases Portal.
- eCourts India Services.
- National Judicial Data Grid.
- `https://ecourtsindia.com/api/docs`.

CaseOps-compliant interpretation:

- Historical judgments, stay orders, interim relief, adjournments, and forum
  outcomes may support controlled predictive signals when the output shows
  sample size, confidence band, source IDs, limitations, and feature
  explanation.
- Judge favorability, win/loss framing, strictness/aggressiveness, and
  settlement inclination are allowed only as controlled predictive analytics.
  They must be statistical and source-backed, never reputation labels or LLM
  intuition.
- If source coverage is below the configured sample threshold, output
  `insufficient_evidence`.
- No use of `ecourtsindia.com/api/docs` unless it is verified as official,
  lawful, reliable, and permitted for this use. Treat it as unverified.
- NJDG is not assumed available and is not per-judge decision data unless a
  verified source contract proves otherwise.

### 3.6 District Court Judgment Integration

PDF problem:

- Most Indian litigation begins at district courts.
- Existing legal research focuses on Supreme Court and High Courts.
- Law firms require district court precedents, trial court reasoning, local
  court trends, and lower-court procedural orders.

PDF proposed layer:

- District Court Legal Intelligence Layer.
- Integrate district court judgments and searchable orders.

PDF District Court Search filters:

- District.
- State.
- Judge.
- Case type.
- Sections involved.
- Order date.

PDF Trial Court Analytics:

- Average disposal time.
- Bail tendencies.
- Conviction/acquittal ratios.
- Frequently cited sections.

PDF AI Summaries:

- Facts summary.
- Issues involved.
- Final order.
- Key observations.
- Important precedents cited.

PDF suggested sources:

- eCourts District Court Services.
- NJDG District Court Data.
- Indian Kanoon District Judgments.

CaseOps-compliant interpretation:

- Start with a source framework and one verified district/source pilot.
- Do not promise district judgments unless official/licensed source access is
  verified.
- Bail tendencies, conviction/acquittal ratios, and local-court procedural
  patterns may become controlled predictive signals only after source lineage,
  sample-size thresholds, confidence-band methods, and limitation copy are in
  place.
- Procedural orders and proceeding sheets are higher-value first than broad
  lower-court precedents because source access is fragmented.

### 3.7 Daily Proceeding Sheet Absorption

PDF problem:

- Daily proceeding sheets/order sheets contain next hearing dates, filing
  defects, compliance directions, counsel appearances, and interim observations.
- Manual tracking causes missed deadlines and operational inefficiency.

PDF proposed engine:

- Automatically ingest, parse, summarize, and structure proceeding sheets.

PDF features:

- Detect new proceeding sheets.
- Download PDFs automatically.
- Extract metadata.
- Generate summaries.
- Create AI alerts for filing replies, affidavit filing, defect removal, and
  similar compliance events.
- Generate hearing chronology, orders passed, compliance history, and filing
  status.
- Extract deadlines.
- Classify court directions.
- Generate next-action recommendations.

CaseOps-compliant interpretation:

- This is the best first product slice because CaseOps already has matter
  hearings, court orders, timeline, tasks, deadlines, reminders, court sync
  jobs, document processing, and audit.
- Automated detection is allowed only where the source is official, permitted,
  and not captcha/session-gated. Otherwise support manual upload/import.
- AI alerts must be reviewable, source-linked, and auditable before becoming
  deadlines or external notifications.

### 3.8 Tribunal Coverage Expansion

PDF problem:

- Law firms work across tribunals and quasi-judicial bodies.
- Data access is fragmented.
- Legal AI systems often miss tribunal ecosystems.

PDF target tribunals:

- Financial and corporate: NCLT, NCLAT, DRT, DRAT, SAT.
- Taxation: ITAT, GST Tribunals.
- Consumer and civil: NCDRC, State Consumer Forums.
- Service and administrative: CAT.
- Environmental: NGT.
- Arbitration: DIAC, MCIA.

PDF features:

- Search by tribunal, bench, matter type, act/section, counsel, and date.
- AI summaries with legal issue, bench reasoning, outcome, compliance direction,
  and appeal possibility.
- Forum-wise strategy intelligence, for example NCLT proof emphasis, consumer
  forum document emphasis, CAT procedural-compliance focus.

CaseOps-compliant interpretation:

- Build a source framework and metadata model before bulk tribunal ingestion.
- Start with official/licensed sources only and one pilot tribunal family.
- "Outcome" in summaries means the actual order result, not a forecast.
- "Forum-wise strategy" must cite source decisions/orders and degrade when
  source history is thin.

### 3.9 Future Strategic Enhancements

PDF asks:

- Litigation strategy AI: best precedents, strongest arguments, opponent
  pleading weaknesses, success probability.
- AI-based case risk score: financial risk, delay risk, adverse-order
  probability, settlement recommendation.
- Multi-lawyer collaboration workspace: shared notes, internal strategy
  discussion, evidence tagging, timeline collaboration.
- Legal knowledge graph connecting judges, cases, advocates, sections,
  precedents, and tribunals.

CaseOps-compliant interpretation:

- Strategy AI overlaps the existing Litigation Strategy and Escalation Planner
  PRD; this PRD extends it with litigation-intelligence source inputs and
  controlled predictive summaries.
- Success probability, adverse-order probability, matter risk score, and delay
  risk are in scope only under the controlled predictive intelligence policy.
- Financial/delay risks may be workflow signals when based on matter data or
  source-backed procedural timelines.
- The legal knowledge graph is in scope as a source-linked relationship graph;
  any graph-derived predictive signal must disclose the edges and source
  records that support it.

### 3.10 Recommended Architecture From PDF

PDF backend components:

- Court crawlers.
- Tribunal scrapers.
- OCR pipeline.
- Metadata extraction.
- Legal LLM.
- Summarization engine.
- Vector search.
- Judgment classifier.
- Hearing prep dashboard.
- Bench analytics.
- Timeline engine.
- Compliance tracker.

CaseOps interpretation:

- Prefer "connectors" or "source adapters" over generic crawlers/scrapers.
- Every source adapter needs source URL, source family, permission status,
  parser version, ingestion run, and lineage.
- Use the existing timeline engine, compliance/task/deadline primitives, and
  Postgres/pgvector path.
- Classification outputs must be bounded to source-backed labels, refusal, or
  `needs_review`.

### 3.11 Business Impact and Roadmap From PDF

PDF impact claims:

- Reduced manual research.
- Automated case tracking.
- Faster hearing preparation.
- Judge intelligence.
- Tribunal analytics.
- Litigation prediction.
- Better hearing preparation.
- Faster updates.
- Improved transparency.

PDF roadmap:

- Phase 1: proceeding sheet ingestion, district court coverage, AI summaries,
  timeline generation.
- Phase 2: bench intelligence, hearing preparation, cross-examination generator.
- Phase 3: outcome prediction, legal strategy AI, voice courtroom simulator.

CaseOps roadmap correction:

- Proceeding sheet ingestion stays Phase 1.
- District and tribunal source coverage must start with source policy and a
  verified-source framework before broad ingestion.
- Affidavit hearing prep can run early because it depends mostly on tenant
  documents and existing OCR/drafting foundations.
- Outcome prediction is approved only as controlled predictive intelligence:
  source-backed, explainable, confidence-banded, tenant-gated, audited, and
  human-reviewed.
- Voice simulator is deferred.

## 4. Current Repo Truth Table

Status values are constrained to Implemented, Partial, and Missing. "Partial"
can include an existing surface that must be corrected before extension.

| PDF capability | Current status | Repo evidence | Gap for this PRD |
| --- | --- | --- | --- |
| Matter timeline | Implemented | `services/matter_timeline.py`, `GET /api/matters/{id}/timeline`, `/app/matters/[id]/timeline`, `test_legalworkspace_matter_timeline.py` | Use it as the proceeding-sheet event spine. |
| Matter hearings and hearing packs | Implemented | `MatterHearing`, `HearingPack`, `services/hearing_packs.py`, `/app/matters/[id]/hearings`, hearing-pack routes | Add proceeding-sheet driven updates and affidavit prep entry points. |
| Court orders/order sheets | Implemented / Verified for LI-S1 V1 | `MatterCourtOrder`, `MatterProceedingSignal`, `services/proceeding_intelligence.py`, `GET /api/matters/{matter_id}/proceeding-intelligence`, `POST /api/matters/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract`, hearings UI, `tests/test_proceeding_intelligence.py` | Deterministic source-text extraction, task/deadline creation, idempotency, and timeline enrichment exist. Broad automatic daily monitoring across every verified source remains pending. |
| Court sync / source adapters | Partial | `services/court_sync_sources.py`, `MatterCourtSyncJob`, `services/authority_sources.py`, adapters for SC, Delhi/Bombay/Karnataka/Madras/Telangana HCs, Central Delhi District public posture rail, LI-S4 legal source registry/readiness entries | Adapters are limited; central Delhi/eCourts source records public posture only because case retrieval is captcha/session-gated; no NJDG/eCourts API assumption. |
| Document upload/OCR/parsing | Partial | `MatterAttachment`, `document_processing.py`, `ocr.py`, malware/quality gates, PDF viewer and annotations, LI-S2 affidavit intelligence over raw chunks | Affidavit document classification and source-linked hearing-prep extraction exist; broader OCR/parser coverage and production quality gates remain partial. |
| Affidavit drafting templates | Implemented | `DraftTemplateType.AFFIDAVIT`, `REPLY_COUNTER_AFFIDAVIT`, `drafting_prompts.py`, `draft_type_validators.py` | Drafting exists separately from LI-S2 affidavit intelligence; future work may connect reviewed question/gap outputs into drafting templates. |
| Affidavit analyzer | Implemented / Verified | `services/affidavit_intelligence.py`, `AffidavitIntelligenceRun`, `AffidavitStatement`, `/api/matters/{matter_id}/affidavit-intelligence`, `/api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze`, documents UI, `tests/test_affidavit_intelligence.py` | LI-S2 V1 uses raw attachment chunks only, deterministic extraction, source quotes, review-required flags, and matter-scoped audit. |
| Cross-examination question generator | Implemented / Verified | `AffidavitQuestion`, `services/affidavit_intelligence.py`, documents UI question bank, source quotes/chunks, `tests/test_affidavit_intelligence.py` | LI-S2 V1 generates source-grounded preparation questions only; no unsupported legal advice, emotion, voice, or biometric scoring. |
| Mock hearing simulator | Implemented / Verified | `services/mock_hearing.py`, `MockHearingSession`, `MockHearingQuestion`, `MockHearingResponse`, `/api/matters/{matter_id}/mock-hearings`, `/app/matters/[id]/hearings`, `tests/test_mock_hearing.py`, hearings page tests | LI-S3 V1 is text-only, deterministic, source-backed, and uses LI-S2 affidavit question banks. |
| Voice-enabled simulator | Missing | No speech workflow in product code | Defer until privacy/consent/provider policy is approved. |
| Judge/court profiles | Implemented | `Court`, `Judge`, `JudgeAppointment`, `JudgeAlias`, `routes/courts.py`, `/app/courts`, `/app/courts/judges/[judge_id]` | Usable as the identity and source-link foundation for controlled predictive analytics. |
| Bench to judge resolution | Implemented | `MatterCauseListEntry.judges_json`, `services/bench_resolver.py`, `test_bench_resolver.py` | Use for bench-specific context and proceeding-sheet bench links. |
| Evidence-only bench context for drafting | Implemented | `services/bench_strategy_context.py`, `BenchContextCard`, `test_bench_strategy_context.py` | Preserve as the safe baseline. |
| Bench strategy panel | Partial | `services/bench_strategy.py`, `BenchStrategyPanel`, L-A/L-B/L-C derived layers | Good citation/statute aggregation foundation; LI-S7 adds controlled predictive contracts rather than opaque prediction. |
| Predictive bench toggle | Partial | `tenant_ai_policies.predictive_bench_strategy_enabled`, `TenantAIPolicyCard`, `test_pg107_predictive_bench.py` | Already usable as the tenant opt-in gate. Needs broader controlled-predictive semantics and audit discipline. |
| Citation graph | Partial | `AuthorityCitation`, `citation_extraction.py`, `authority_treatments.py`, `judge_authority_affinity` | Useful graph substrate; not a full legal knowledge graph. |
| Statute model and statute references | Implemented | `Statute`, `StatuteSection`, `AuthorityStatuteReference`, `/app/statutes`, `statute_resolver.py` | Extend coverage as tribunal/district sources require. |
| District court source support | Partial | `forum_level=lower_court`, forum catalog validation, Central Delhi public source posture adapter, lower-court research filter, LI-S4 registry entries for district/session courts marked blocked/planned | No production district judgment corpus, no verified broad eCourts/NJDG data path, and no automated captcha/session-gated scraping. |
| Tribunal source support | Partial | `forum_level=tribunal`, NCLT/NCLAT/DRT format profiles, template recommender tribunal paths, research filter, LI-S4 registry entries for NCLT/NCLAT/DRT/DRAT/ITAT/NGT/CAT/consumer forums marked planned | No tribunal corpus ingestion or tribunal profile intelligence until lawful source adapters and corpus-quality proof exist. |
| Legal knowledge graph | Partial | LI-S11 `legal_knowledge_graph_*` matter graph tables, `/api/matters/{matter_id}/legal-knowledge-graph`, `/app/matters/[id]/knowledge-graph`, authority citations, judge decision index, statute focus | Matter-scoped graph foundation exists. Corpus-scale graph analytics, broad visual exploration, and cross-case/tribunal graph expansion remain deferred. |
| Compliance tracking | Partial | Matter tasks/deadlines, calendar feed, reminders, notification rules, `MatterCourtOrder` stay flags, LI-S1 high-confidence proceeding-signal task/deadline creation | Proceeding-sheet derived tasks/deadlines exist with review flags and audit. External client notifications and broader calendar delivery remain deferred. |
| Human review gates | Partial | Draft approval gates, recommendation decisions, hearing-pack review, audit, LI-S6 read-only litigation-intelligence review page, LI-S9 review mutations | Review-required states are visible across LI-S1/S2/S3/S5/S7; LI-S9 adds accept/reject/mark-reviewed/note actions for the LI queue. Broader workflow assignment/escalation remains pending. |
| Tenant isolation and audit | Implemented foundation | `assert_access`, matter grants, ethical walls, `AuditEvent`, route capabilities | Every new LI table/route must prove tenant/matter isolation and audit. |
| Corpus/vector quality | Partial | Voyage/pgvector/reranker path, corpus-ingest skill, authority retrieval | New district/tribunal/public-law slices must meet the 4.8/5 readiness gate before production claims. |

### 4.1 Predictive-Related Repo Truth

Status values: Already usable, Partial, Missing, Unsafe/stale-doc.

| Surface | Status | Repo truth | LI-S7 implication |
| --- | --- | --- | --- |
| `tenant_ai_policies.predictive_bench_strategy_enabled` | Already usable | `TenantAIPolicy`, admin route, resolver, UI card, tests | Use as the first tenant opt-in gate for predictive litigation intelligence. |
| `bench_strategy.py` | Partial | Returns bench judge IDs, indexed decision count, authority/statute aggregates, evidence quality, disclaimer | Reuse its materialized-layer foundation; LI-S7A adds typed predictive contracts and source-backed confidence bands. |
| `bench_analysis_layers.py` | Already usable | Builds L-A judge decision index, L-B authority affinity, L-C statute focus | Primary deterministic data source for LI-S7A bench signals. |
| `bench_strategy_context.py` | Partial | Has `mode=predictive` and descriptive outcome counts when policy is enabled | Useful proof of opt-in behavior, but the shape lacks confidence bands, evidence objects, and unified audit/run persistence. |
| `recommendations.py` | Partial | Citation-verified recommendations and outcome-bias reranking over `AuthorityDocument.outcome_label` | Reusable as an input pattern for later LI-S10 review workflows, but not the predictive contract. |
| `appeal_strength.py` | Partial | Deterministic argument-completeness analyzer with policy-mode echo | Useful risk/evidence-gap input; currently blocks probability language and is not a predictive scorecard. |
| `litigation_strategy.py` | Partial | Citation-grounded route planner with strong forbidden-probability gates | Must be revised in a later slice before it consumes LI-S7 outputs. |
| `hearing_packs.py` | Already usable | Matter-scoped hearing-pack generation with ModelRun and audit | Good source for later hearing-prep context; no mock-hearing scoring today. |
| Matter review / strategy entries | Partial | `matter_strategy_entries`, recommendations decisions, matter audit | Useful human-review substrate; no dedicated predictive review workflow yet. |
| Predictive data contract/API foundation | Implemented and verified | `schemas/predictive_intelligence.py`, `services/predictive_intelligence.py`, `predictive_signal_*` tables, matter route tests | LI-S7A is complete for typed source-backed outputs, tenant policy gate, audit, and insufficient-evidence fallback. |
| Outcome-classification/backfill layer | Implemented and verified | `services/predictive_outcomes.py`, `scripts/backfill_predictive_outcomes.py`, `predictive_outcome_classifications`, `predictive_outcome_aggregate_snapshots`, tests | LI-S7B is complete for deterministic/controlled-label classification, official-source allowlist, aggregate snapshots, and stale cleanup. |
| Matter cockpit Predictive Intelligence UI | Implemented and verified | `/app/matters/[id]/predictive-intelligence`, nav tab, strict frontend schemas/tests | LI-S7C is complete for supported, disabled, insufficient-evidence, disclaimer, and source-link states. |
| Voice/emotion system | Missing | No voice simulator or audio metrics | Keep deferred; only observable text/session metrics may enter LI-S7A. |
| Older blanket no-prediction docs | Unsafe/stale-doc | Older PRD sections and comments still ban all prediction language | Replace with controlled predictive policy in this addendum; later cleanup can align older docs and comments. |

## 5. Source-Data Policy

### 5.1 Allowed Source Classes

| Source class | Default status | Rules |
| --- | --- | --- |
| Official Supreme Court site and approved public datasets | Allowed after connector verification | Store source URL, fetch time, adapter version, parser version, and source family. |
| Official High Court sites | Allowed after per-court connector verification | Per-court behavior differs; no generic scraper without source-specific proof. |
| Official district court/eCourts public pages | Conditional | Do not assume API access. Do not bypass captcha/session restrictions. Use manual upload if unattended retrieval is not permitted. |
| NJDG | Conditional/deferred | Treat as aggregate analytics only until verified; do not use for per-judge decision claims. |
| Official tribunal sites | Conditional | One tribunal family at a time; record terms, source URL, bench metadata, and parser quality. |
| India Code and official gazette sources | Allowed | Use for statutes and rules. |
| Paid commentary or databases | Deferred until licensed | SCC, Manupatra, and similar sources require contract, usage scope, and SEC-024 tracking. |
| Indian Kanoon | Licensed, default off | Use only with a funded licensed API token and machine-verifiable terms, permitted-use, retention, cost, and budget metadata; do not treat it as an official source. |

### 5.2 Ingestion Quality Rules

Production public-law ingestion must follow the CaseOps corpus contract:

1. Fetch or receive the source document.
2. Validate source legality, file type, and safety.
3. Parse with the best parser for that source family.
4. OCR only when needed; reject low-quality OCR garbage.
5. Run structured metadata extraction before embedding.
6. Normalize title, parties, judges, bench, sections, citations, dates, and
   source lineage.
7. Build title/metadata chunks only after real metadata is available.
8. Embed with Voyage `voyage-4-large` in production.
9. Keep reranking enabled where the PRD requires it.
10. Benchmark via HNSW retrieval quality, not extraction samples.
11. Do not call a new source family production-ready below 4.8/5.

### 5.3 Controlled Predictive Intelligence Policy

- Every substantive legal output must cite matter documents, proceeding sheets,
  judgments, statutes, or tribunal orders.
- Prediction, favorability, likelihood, inclination, and risk surfaces are
  allowed only when source data exists and the output shows sample size,
  confidence band, supporting judgment/order IDs, explainable features,
  limitations, tenant AI policy gate, human-review state, audit trail, and the
  label "decision support, not legal advice."
- When evidence is weak or below the configured sample threshold, output
  `insufficient_evidence`; do not invent a prediction.
- AI may summarize or classify cited evidence, but predictions must never be
  based only on LLM intuition.
- Emotional or psychological scoring is prohibited as diagnosis. Mock-hearing
  scoring may use observable session metrics only, such as answer consistency,
  citation support, unsupported new facts, response delay, and changed answers.
- Customer matter data stays tenant-scoped and is never used for cross-tenant
  training without explicit opt-in.

## 6. Additive User Stories

| Story ID | User story |
| --- | --- |
| US-LI-001 | As a lawyer, I can see source-backed proceeding sheet updates in the matter timeline, with next hearing date, directions, defects, counsel appearances, and source PDF. |
| US-LI-002 | As a clerk, I can review extracted court directions before they become tasks, deadlines, or reminders. |
| US-LI-003 | As a litigator, I can select a chief affidavit and receive fact, timeline, contradiction, evidence-gap, and cross-examination prep outputs grounded in the affidavit and exhibits. |
| US-LI-004 | As a lawyer, I can run a text mock hearing using approved question sets and preserve the prep report under the matter. |
| US-LI-005 | As an admin, I can see which district/session/tribunal sources are verified, licensed, blocked, or manual-upload only. |
| US-LI-006 | As a researcher, I can search official/licensed district and tribunal orders with filters for forum, bench, case type, section, counsel, and date once those source slices pass quality gates. |
| US-LI-007 | As a senior litigator, I can see controlled predictive bench/forum signals on a specific issue, with citations, sample size, confidence band, feature explanation, and limitations. |
| US-LI-008 | As a strategy reviewer, I can accept, reject, or edit AI-suggested next actions and preserve an audit trail. |
| US-LI-009 | As a knowledge manager, I can inspect a source-linked legal graph connecting cases, judges, advocates, statutes, citations, forums, tribunals, and matter artifacts. |
| US-LI-010 | As a security admin, I can prove every litigation-intelligence feature respects tenant isolation, matter access, ethical walls, audit, and provider policy. |
| US-LI-011 | As a tenant admin, I can enable or disable predictive litigation intelligence before users see favorability, likelihood, risk, or hearing-score surfaces. |
| US-LI-012 | As a partner, I can see `insufficient_evidence` instead of a prediction when source coverage is too thin. |
| US-LI-013 | As a litigation partner, I can inspect one matter-level review surface for pending source-backed proceeding, affidavit, mock-hearing, bench, and predictive intelligence items before relying on them. |

## 7. Additive Test IDs

Functional:

| Test ID | Verification |
| --- | --- |
| FT-LI-001 | Proceeding-sheet import stores source snapshot, order record, extracted directions, and timeline event. |
| FT-LI-002 | Proceeding-sheet extraction promotes a reviewed filing direction into a matter task/deadline. |
| FT-LI-003 | Proceeding-sheet extraction refuses or marks uncertain when no date/direction is source-supported. |
| FT-LI-004 | Affidavit analysis extracts facts, dates, figures, entities, contradictions, and evidence gaps with page/paragraph anchors. |
| FT-LI-005 | Cross-examination generator creates categorized questions, each linked to affidavit text, exhibit, or matter fact. |
| FT-LI-006 | Mock hearing session records question, answer, elapsed time, reviewer notes, and rubric feedback. |
| FT-LI-007 | Mock hearing feedback uses observable performance metrics only and contains no medical, mental-health, biometric, or personality diagnosis. |
| FT-LI-008 | Source registry marks unverified eCourts/NJDG/API sources as unavailable until verified. |
| FT-LI-009 | District/session source pilot ingests only official/licensed documents and records lineage. |
| FT-LI-010 | Tribunal source pilot supports tribunal, bench, matter type, act/section, counsel, and date filters after quality gate. |
| FT-LI-011 | Bench/forum intelligence returns cited patterns with source documents, sample size, evidence quality, and limitation note. |
| FT-LI-012 | Controlled predictive outputs include source IDs, sample size, confidence band, feature explanation, limitation note, tenant-policy gate, audit event, and "decision support, not legal advice" disclaimer. |
| FT-LI-013 | Legal graph API returns source-linked nodes/edges for case, citation, judge, statute, advocate, tribunal, and matter artifact. |
| FT-LI-014 | Legal graph UI filters by source family, forum, judge, section, and date without leaking tenant-private graph nodes. |
| FT-LI-015 | Weak evidence returns `insufficient_evidence` and missing-data requirements, not an invented prediction. |
| FT-LI-016 | Supported predictive signals cannot render unless at least one evidence source ID is attached. |
| FT-LI-017 | Tenant policy disabled returns a blocked/disabled state before any predictive output is generated. |
| FT-LI-018 | Litigation intelligence review API returns matter-scoped, source-linked review items from existing LI-S1/S2/S3/S5/S7 records without creating new predictions. |
| FT-LI-019 | Litigation intelligence review UI renders grouped items, source links, limitation copy, disclaimer, and empty/loading/error states while rejecting unknown source types. |

Non-functional:

| Test ID | Verification |
| --- | --- |
| NFT-LI-001 | Proceeding-sheet import is idempotent by source URL/hash and does not duplicate timeline events. |
| NFT-LI-002 | Proceeding-sheet extraction p95 stays within the agreed SLO for a 20-page order sheet. |
| NFT-LI-003 | Affidavit analysis handles a 100-page affidavit bundle without runaway memory or provider timeout. |
| NFT-LI-004 | New public-source retrieval slice reaches rating >= 4.8/5 before production-ready claim. |
| NFT-LI-005 | Source connector health dashboard shows last success, last failure, parser version, and blocked reason. |
| NFT-LI-006 | Legal graph materialization job completes within the agreed nightly window on current corpus size. |
| NFT-LI-007 | Predictive signal generation remains deterministic and bounded for LI-S7A; later model jobs must be asynchronous and auditable. |

Security:

| Test ID | Verification |
| --- | --- |
| SEC-LI-001 | Every LI matter route enforces company membership, active membership, matter access, team scoping, and ethical walls. |
| SEC-LI-002 | Cross-tenant matter, affidavit, proceeding sheet, simulator session, and graph-node access returns 404 or 403 as appropriate. |
| SEC-LI-003 | Public-law corpus search never joins tenant-private notes, simulator answers, drafts, or affidavit prep reports into another tenant's response. |
| SEC-LI-004 | Prompt-injection content inside a source PDF cannot override extraction schema or ask the model to leak matter data. |
| SEC-LI-005 | Provider payloads and simulator answers are redacted in logs and audited by ModelRun without raw secrets. |
| SEC-LI-006 | Source adapters fail closed on unverified API access, captcha/session gate, broken TLS, or license uncertainty. |
| SEC-LI-007 | Human review is required before proceeding-sheet directions create external notifications or client-facing updates. |
| SEC-LI-008 | Admin source-policy changes and AI-policy changes are audited with before/after values. |
| SEC-LI-009 | Predictive intelligence endpoint enforces tenant, matter access, restricted matter grants, ethical walls, and audit. |
| SEC-LI-010 | Predictive outputs never join tenant-private matter facts into another tenant's public-law or bench/forum response. |

## 8. Slice Plan

### LI-S0: PRD and Source Policy

Purpose:

- Establish this PRD as the implementation contract before product code.
- Replace blanket no-prediction language with the controlled predictive
  intelligence policy.
- Create a source-policy gate for district, eCourts, NJDG, tribunal, and
  third-party sources.

User stories:

- US-LI-005.
- US-LI-010.

API/backend changes:

- No product behavior change in LI-S0.
- If implementation approval allows docs-only changes, link this addendum from
  `docs/PRD_CODEX_2026-04-23.md`.
- Add or update a source-policy section or ledger naming allowed, conditional,
  blocked, and deferred source classes.
- Record that existing `predictive_bench_strategy_enabled` is the initial
  tenant opt-in gate, but every predictive surface must add source lineage,
  confidence band, feature explanation, limitation note, human review, and
  audit.

DB models/migrations:

- None in LI-S0.

Frontend pages/components:

- None in LI-S0.

AI prompts/providers:

- None in LI-S0.
- Draft the approved wording for later prompts:
  "Use only cited source text and matter-scoped facts. Predictive claims must
  be derived from cited evidence, sample size, confidence band, and explainable
  features. If the evidence is thin, return insufficient_evidence. Do not
  guess from LLM intuition. Mark all outputs decision support, not legal
  advice."

Source-data rules:

- Official/licensed sources only.
- eCourts/NJDG/API access is unverified until proven by source-policy evidence.
- No captcha/session bypass.
- Indian Kanoon, SCC, Manupatra, and similar sources require license/terms
  approval before use.

Tests:

- Docs verification only:
  - `rg -n "controlled predictive|insufficient_evidence|decision support, not legal advice|confidence band" docs/PRD_LITIGATION_INTELLIGENCE_EXPANSION_2026-05-11.md`
    should prove the controlled predictive policy is captured.
  - `rg -n "voyage-4-large|4.8/5|official/licensed|eCourts" docs/PRD_LITIGATION_INTELLIGENCE_EXPANSION_2026-05-11.md`
    should prove source policy is captured.

Security/tenant isolation checks:

- No LI-S0 runtime surface; product implementation status is tracked in each
  later slice.
- Confirm LI-S1 through LI-S7 require SEC-LI-* tests before shipping.

Acceptance criteria:

- This file exists and is reviewed.
- Canonical PRD linkage is planned or added in a docs-only implementation.
- Predictive PDF asks are converted into controlled, explainable, source-backed
  product requirements.
- Source policy is explicit enough for a later implementer not to guess.
- LI-S0 remains docs/source-policy only; LI-S7A/B/C product implementation is
  tracked in the LI-S7 section below.

### LI-S1: Proceeding Sheet Intelligence

Status:

- Implemented and verified as LI-S1 V1. Backend verification covers raw
  `MatterCourtOrder.order_text` extraction, insufficient-source fallback,
  court-sync rerun idempotency, ambiguous relative deadline handling, generated
  task/deadline audit, restricted/team/ethical-wall route denial, and migration
  order.
- V1 does not create a parallel proceeding-sheet module. It uses
  `MatterCourtOrder`, `MatterProceedingSignal`, `MatterTask`,
  `MatterDeadline`, matter timeline enrichment, and the hearings page.

Purpose:

- Convert daily proceeding sheets/order sheets into matter timeline events,
  reviewed compliance directions, deadlines, tasks, and hearing updates.

User stories:

- US-LI-001.
- US-LI-002.
- US-LI-008.
- US-LI-010.

API/backend changes:

- Implemented service:
  - `apps/api/src/caseops_api/services/proceeding_intelligence.py`.
- Implemented endpoints:
  - `GET /api/matters/{matter_id}/proceeding-intelligence`.
  - `POST /api/matters/{matter_id}/court-orders/{order_id}/proceeding-intelligence/extract`.
- Reuses existing `MatterCourtOrder`, `MatterTask`, `MatterDeadline`,
  matter timeline, and audit services.
- Extracts:
  - metadata: court, forum, case number, party names, order date, next date,
    bench/judge, counsel appearances, stage, item number.
  - directions: filing reply, affidavit, defect removal, payment/deposit,
    service, notice, compliance report, production of records.
  - uncertainty: supported, review-required, insufficient source text, or
    insufficient evidence.
- Court-sync reruns use source-stable dedupe keys so the same imported source
  order does not duplicate proceeding signals, tasks, deadlines, or timeline
  entries.

DB models/migrations:

- `matter_proceeding_signals`:
  - `id`, `company_id`, `matter_id`, `court_order_id`, `sync_run_id`,
    `signal_type`, `signal_text`, `action_required`, `due_on`, `hearing_on`,
    `order_kind`, `confidence_label`, `source_snippet`, `review_status`,
    `generated_task_id`, `generated_deadline_id`, `source_stable_key`,
    `extraction_method`, `parser_version`, timestamps.
- Migration:
  - `apps/api/alembic/versions/20260511_0004_proceeding_intelligence.py`.
- No separate `proceeding_sheets` or `proceeding_directions` tables exist in
  V1; that earlier normalized plan is superseded by the smaller
  `MatterCourtOrder` plus `MatterProceedingSignal` implementation.

Frontend pages/components:

- Implemented dense Proceeding Intelligence section on
  `/app/matters/[id]/hearings`.
- The section shows recent source orders, extracted directions, compliance due
  dates, generated task/deadline links, review-required states, and source
  snippets.
- Matter timeline enrichment exists through proceeding-signal timeline
  integration. A dedicated review drawer is not implemented in V1.

AI prompts/providers:

- Implemented V1 is deterministic and reads raw/source `order_text` only.
- No summary/generated fallback and no LLM path is active in LI-S1 V1.
- If a future LLM path is added, it must use structured extraction from source
  order text only, persist ModelRun, and keep page/paragraph/source anchors.
- Ambiguous relative deadlines such as "within two weeks" remain
  review-required and do not create `due_on`, tasks, or deadlines unless there
  is a clear anchor such as "from the date of this order."

Source-data rules:

- Automatic polling only for verified official source adapters.
- Manual upload allowed for unsupported/captcha-gated sources.
- No eCourts/NJDG API assumption.
- Store source URL, source family, fetch timestamp, parser version, and hash.

Tests:

- FT-LI-001, FT-LI-002, FT-LI-003.
- NFT-LI-001, NFT-LI-002.
- SEC-LI-001, SEC-LI-002, SEC-LI-004, SEC-LI-006, SEC-LI-007.
- Existing regression:
  - matter timeline tests.
  - hearing/court-sync tests.
  - audit tests.

Security/tenant isolation checks:

- All routes call matter access checks.
- Directions cannot be promoted across tenant or matter.
- External notifications are not sent until review is complete.
- Audit every import, extraction, review decision, promotion, and deletion.

Acceptance criteria:

- A user can extract directions from a source-backed court order, see
  proceeding intelligence on the hearings page, and receive generated
  task/deadline links for high-confidence anchored directions.
- Unsupported or unverified source access is explicit and recoverable.
- No duplicate signals, tasks, deadlines, or timeline events on repeated import
  or extraction of the same source order.

### LI-S2: Affidavit Hearing Prep

Status:

- Implemented and verified as LI-S2 V1. Backend verification covers raw
  attachment chunks only, insufficient-source fallback, cross-tenant and
  restricted/team/ethical-wall denial, source-quoted statements/questions,
  review-required low-confidence questions, audit, rerun behavior, validated
  affidavit document type values, and migration order.
- Frontend verification covers the matter documents page section, source
  quotes, question bank, review-required state, empty/loading/error states, and
  forbidden legal-advice/emotion/biometric/psychological copy.

Purpose:

- Analyze chief affidavits and exhibits for hearing preparation and generate
  source-linked cross-examination prep questions.

User stories:

- US-LI-003.
- US-LI-008.
- US-LI-010.

API/backend changes:

- Implemented service:
  - `apps/api/src/caseops_api/services/affidavit_intelligence.py`.
- Implemented endpoints:
  - `GET /api/matters/{matter_id}/affidavit-intelligence`.
  - `POST /api/matters/{matter_id}/attachments/{attachment_id}/affidavit-intelligence/analyze`.
- Reuse `MatterAttachment` for affidavit source documents.
- Extracts:
  - facts.
  - claims.
  - admissions.
  - dates.
  - financial figures.
  - names/entities.
  - exhibit references.
  - inconsistencies within the affidavit.
  - inconsistencies against selected matter documents.
  - missing support documents.
  - source-grounded cross-examination question categories.
- V1 does not expose separate review/approve/export mutation endpoints.
  Review-required status is persisted and surfaced for lawyer review.

DB models/migrations:

- `affidavit_intelligence_runs`:
  - `id`, `company_id`, `matter_id`, `attachment_id`, `status`,
    `extraction_method`, `parser_version`, `source_hash`,
    `source_char_count`, `missing_data_json`, `model_run_id`,
    `created_by_membership_id`, timestamps.
- `affidavit_statements`:
  - `id`, `company_id`, `matter_id`, `run_id`, `attachment_id`,
    `source_chunk_id`, `source_chunk_index`, `page_reference`,
    `statement_type`, `statement_text`, `source_quote`, `confidence_label`,
    `review_status`, timestamps.
- `affidavit_questions`:
  - `id`, `company_id`, `matter_id`, `run_id`, `attachment_id`,
    `statement_id`, `source_chunk_id`, `source_chunk_index`,
    `page_reference`, `category`, `question_text`, `reason`,
    `source_quote`, `confidence_label`, `review_required`,
    `review_status`, timestamps.
- Migration:
  - `apps/api/alembic/versions/20260511_0005_affidavit_intelligence.py`.

Frontend pages/components:

- Implemented "Affidavit intelligence" section on
  `/app/matters/[id]/documents`.
- Supports attachments marked `affidavit`, `chief_affidavit`, or
  `counter_affidavit`.
- Shows:
  - extracted timeline.
  - admissions.
  - contradictions.
  - evidence gaps.
  - question set grouped by category.
  - source quotes.
  - review-required states.
  - generate/analyze action.
  - empty, loading, and error states.

AI prompts/providers:

- Implemented V1 is deterministic and analyzes raw `MatterAttachmentChunk`
  text only. It does not use generated summaries.
- No LLM path is active in LI-S2 V1. If a future LLM path is added, it must
  use the configured provider, persist ModelRun, and require JSON schema and
  source anchors:
  - `source_anchor`: page, paragraph, quote, exhibit id when available.
  - `question_category`.
  - `question`.
  - `why_it_matters`.
  - `supporting_source_ids`.
  - `needs_human_review`.
- No "contradiction probability" or legal outcome risk score.

Source-data rules:

- Primary source is tenant-private affidavit and selected matter documents.
- Public-law retrieval must stay tenant-scoped on private context and
  citation-grounded on public authorities.
- Do not include client prep outputs in shared corpus.

Tests:

- FT-LI-004, FT-LI-005.
- NFT-LI-003.
- SEC-LI-001, SEC-LI-002, SEC-LI-003, SEC-LI-004, SEC-LI-005.
- Structural tests:
  - no probability language.
  - no unsupported legal risk score.
  - every question has a source anchor or `needs_review`.

Security/tenant isolation checks:

- Cross-tenant attachment id cannot be analyzed.
- Ethical walls override role access.
- Analysis results are matter-private.
- If a future LLM path is enabled, ModelRun audit must record provider, model,
  tenant, matter, actor, tokens, latency, and status without storing secrets.

Acceptance criteria:

- A lawyer can select a chief affidavit, generate analysis, review source
  anchors, and produce a categorized question set.
- Every material output is anchored to affidavit/exhibit/matter source text or
  clearly marked as needing review.

### LI-S3: Mock Hearing Simulator V1

Status:

- Implemented and verified as LI-S3 V1. Backend verification passed with
  `tests/test_mock_hearing.py` and migration-order coverage; frontend
  verification passed through the matter hearings page tests, typecheck, and
  production build.

Purpose:

- Provide a text-first, source-linked client/counsel preparation flow using
  approved affidavit question sets.

User stories:

- US-LI-004.
- US-LI-008.
- US-LI-010.

API/backend changes:

- Implemented endpoints:
  - `POST /api/matters/{matter_id}/mock-hearings`
  - `GET /api/matters/{matter_id}/mock-hearings`
  - `GET /api/matters/{matter_id}/mock-hearings/{session_id}`
  - `POST /api/matters/{matter_id}/mock-hearings/{session_id}/responses`
  - `POST /api/matters/{matter_id}/mock-hearings/{session_id}/complete`
- Simulator modes:
  - counsel practice.
  - client preparation.
  - witness preparation.
- V1 is text-first. Voice, audio recording, speech analysis, emotion,
  biometric, psychological, and mental-health scoring are not implemented.

DB models/migrations:

- `mock_hearing_sessions`:
  - `id`, `company_id`, `matter_id`, `source_affidavit_run_id`, `mode`,
    `status`, `created_by_membership_id`, `participant_label`,
    `review_status`, `disclaimer`, scorecard fields, timestamps.
- `mock_hearing_questions`:
  - `id`, `company_id`, `matter_id`, `session_id`,
    `source_affidavit_run_id`, `source_affidavit_question_id`,
    `source_affidavit_statement_id`, `source_attachment_id`,
    `source_chunk_id`, `source_chunk_index`, `page_reference`, `turn_index`,
    `category`, `question_text`, `reason`, `source_quote`,
    `difficulty_label`, `status`, timestamps.
- `mock_hearing_responses`:
  - `id`, `company_id`, `matter_id`, `session_id`, `question_id`,
    `source_affidavit_question_id`, `response_text`,
    `response_word_count`, `elapsed_seconds`, deterministic feedback flags,
    `response_completeness`, `confidence_label`, `feedback_text`,
    `evaluation_json`, `source_quote`, `review_required`, `review_status`,
    timestamps.

Frontend pages/components:

- Implemented compact "Mock hearing" section in the matter hearings page.
- Session UI:
  - current question.
  - typed response field.
  - source quote and source document link.
  - feedback after a response.
  - scorecard metrics.
  - review-required state.
  - empty, loading, and error states.
- Session report surface:
  - consistency issues.
  - unsupported answer points.
  - missing documents.
  - suggested follow-up preparation.

AI prompts/providers:

- Uses approved question set and source anchors from LI-S2 affidavit
  intelligence.
- Implemented V1 uses deterministic response feedback only. There is no LLM
  path in LI-S3 V1; any future LLM path must persist ModelRun metadata, audit
  model use, and remain source-bound.
- Feedback rubric:
  - answer addresses question.
  - answer consistent with affidavit.
  - answer supported by exhibit or source.
  - answer introduces new unsupported fact.
  - answer needs lawyer review.
- Feedback is hearing-preparation decision support, not legal advice.
- No emotional instability detection, stress score, mental-health inference,
  biometric scoring, speech analysis, or outcome prediction.

Source-data rules:

- Use matter-private data only unless the lawyer explicitly adds public-law
  context.
- Do not store audio in V1; no audio recording or speech analysis is present.
- Do not expose simulator reports to client portal unless manually shared by an
  authorized lawyer.

Tests:

- FT-LI-006, FT-LI-007.
- SEC-LI-001, SEC-LI-002, SEC-LI-003, SEC-LI-004, SEC-LI-005.
- Backend tests cover no-question fallback, source-backed session creation,
  response serialization, source-linked deterministic feedback, low-confidence
  review-required behavior, idempotent completion, audit events,
  cross-tenant/restricted/team/ethical-wall denial, and forbidden-language
  scanning.
- Web tests cover start, answer, source quote/link rendering, feedback,
  scorecard, empty state, and forbidden-language scan.

Security/tenant isolation checks:

- Sessions, questions, and responses include company_id and matter_id.
- Access requires matter read plus a new or existing hearing-prep capability.
- Client/witness labels must not create portal access.
- Audit session creation, response submission, and completion.

Acceptance criteria:

- A user can run a text mock hearing from an approved question set and receive
  a preparation report with source-linked, non-predictive feedback.
- The UI displays "not legal advice" before and during a session.

### LI-S4: District/Session/Tribunal Source Framework

Purpose:

- Create the source and ingestion framework required before adding lower-court
  and tribunal intelligence at scale.

Implementation status:

- LI-S4 foundation is implemented in `services/authority_sources.py` as a
  conservative source registry/readiness layer over the existing authority
  adapters.
- Current ingest-ready/public-aggregate sources are limited to official
  Supreme Court and High Court adapters already supported by the repo.
- District court, session court, tribunal, consumer forum, statutory bare-act,
  and arbitration source families are registered for readiness visibility only;
  they are not broad-ingest ready.
- Broad district/session/tribunal ingestion, admin source CRUD, source-run
  persistence, and research filter expansion remain pending.

User stories:

- US-LI-005.
- US-LI-006.
- US-LI-010.

API/backend changes:

- Implemented foundation:
  - `LegalSourceRegistryEntry` static registry entries for source key/name,
    jurisdiction, court/forum, category, official/licensed/manual/internal/test
    source type, adapter availability, access mode, captcha/session-gated flag,
    public-corpus allowance, predictive-aggregate allowance, lineage
    requirements, checked status, and notes.
  - Internal readiness functions:
    - `list_legal_source_registry_entries`
    - `get_legal_source_registry_entry`
    - `is_source_allowed_for_public_corpus`
    - `is_source_allowed_for_predictive_aggregates`
    - `is_source_blocked_for_automated_ingest`
    - `list_public_corpus_authority_source_keys`
    - `list_predictive_aggregate_authority_source_keys`
  - Public corpus source listing and LI-S7 predictive aggregate source
    selection consume only registry-approved official/licensed adapter sources.
- Future admin APIs:
  - `GET /api/admin/legal-sources`
  - `POST /api/admin/legal-sources/{source_id}/verify`
  - `PATCH /api/admin/legal-sources/{source_id}`
  - `GET /api/admin/legal-source-runs`
  - `POST /api/admin/legal-source-runs`
- Future source-family aware ingestion service for:
  - district/session courts.
  - consumer forums.
  - NCLT/NCLAT.
  - DRT/DRAT.
  - ITAT.
  - NGT.
  - CAT.
- Extend research filters to use source family, forum level, tribunal, bench,
  state, district, case type, act/section, counsel, and order date once data
  exists.
- Add connector health and blocked-reason reporting.

DB models/migrations:

- No database migration is required for the LI-S4 foundation because the
  current repo already has a source adapter registry and this slice only needs
  immutable readiness metadata for supported/planned source families.
- Future `legal_source_catalog` when admin verification becomes mutable:
  - `id`, `source_family`, `forum_level`, `forum_name`, `jurisdiction`,
    `state`, `district`, `tribunal_key`, `official_url`, `license_status`,
    `access_status`, `robots_or_terms_status`, `verified_by_membership_id`,
    `verified_at`, `blocked_reason`, timestamps.
- Future `legal_source_ingest_runs`:
  - `id`, `source_id`, `status`, `started_at`, `completed_at`,
    `documents_found`, `documents_ingested`, `documents_skipped`,
    `quality_rating`, `recall_at_10`, `mrr`, `mean_rank`,
    `error_message`, `adapter_version`.
- Extend `AuthorityDocument` only where required:
  - `source_url` if `source_reference` is insufficient.
  - `source_family`.
  - `jurisdiction_path_json`.
  - `license_status`.
  - `ingest_run_id`.
- Prefer additive columns over a parallel authority table.

Frontend pages/components:

- No frontend is implemented in the foundation slice.
- Future: add `/app/admin/legal-sources`.
- Extend `/app/research` filters for source family and forum details.
- Extend `/app/courts` and court profiles to show coverage status.

AI prompts/providers:

- Ingestion metadata extraction uses structured output and source-family
  prompts.
- Public-law embedding uses Voyage `voyage-4-large`.
- Metadata cleanup uses approved high-reliability LLM path where required.
- No model-generated source metadata without source evidence.

Source-data rules:

- Each new source starts as planned, blocked, manual-only, or unverified until
  lawful access and lineage are verified.
- eCourts and NJDG remain blocked/conditional until verified; no API access is
  assumed.
- Do not scrape around captcha/session controls.
- One pilot source family must pass the 4.8/5 gate before scale-out.

Tests:

- FT-LI-008, FT-LI-009, FT-LI-010.
- NFT-LI-004, NFT-LI-005.
- SEC-LI-006, SEC-LI-008, SEC-024 from canonical PRD.
- Corpus quality probe tests for each production-ready source family.

Security/tenant isolation checks:

- Public source catalog has no tenant-private data.
- Admin mutations require admin/owner capability and audit.
- Source ingestion cannot read tenant-private documents.
- Public-law retrieval can join tenant-private context only through existing
  tenant-scoped retrieval paths.

Acceptance criteria:

- Internal ops/service code can see verified/blocked/manual-only source posture.
- Public corpus and predictive aggregate jobs accept only registered
  official/licensed, non-captcha-gated, adapter-backed sources.
- District/session/tribunal/consumer/arbitration planned sources appear in
  readiness output but are not treated as ingest-ready.
- One district/session or tribunal pilot source ingest with full lineage and a
  quality report remains pending.
- Research filters expose source family only when data exists.

### LI-S5: Evidence-Backed Bench/Forum Intelligence

Purpose:

- Deliver bench/forum context from indexed decisions and proceeding/order data,
  including controlled predictive signals only when LI-S7 foundations and
  source-quality gates are satisfied.

Implementation status:

- LI-S5 Predictive Intelligence integration is implemented as an additive
  `bench_context` object on
  `GET /api/matters/{matter_id}/predictive-intelligence`.
- The implementation reuses LI-S7 aggregate snapshots, `judge_decision_index`,
  and source evidence already available to the predictive-intelligence service.
- Weak evidence degrades to `limited_context` or `insufficient_evidence`.
- No separate bench/forum context route, admin UI, ingestion, scraping,
  embedding job, or LLM summarization path is implemented in this slice.

User stories:

- US-LI-007.
- US-LI-008.
- US-LI-010.

API/backend changes:

- Implemented in this slice:
  - Add `BenchContextSummary`, `BenchContextScope`, and
    `ObservedSignalDistribution` response schemas.
  - Add `bench_context` to `PredictiveIntelligenceResponse`.
  - Build bench context from resolved matter bench/judge IDs, LI-S7B aggregate
    snapshots, official/licensed authority evidence, sample size, year window,
    observed distribution, confidence/evidence quality, source evidence, and
    limitation notes.
  - Preserve existing tenant policy gate, matter access, restricted matter,
    team scoping, ethical wall, cross-tenant denial, and audit behavior through
    the existing predictive-intelligence route.
- Future standalone context APIs:
  - `GET /api/matters/{matter_id}/bench-forum-context`
  - `GET /api/courts/{court_id}/forum-context`
  - `GET /api/courts/judges/{judge_id}/evidence-context`
- Inputs:
  - matter issue/practice area.
  - forum level.
  - resolved bench/judge ids.
  - source family filters.
- Outputs:
  - top authorities cited by the bench/forum.
  - top statute sections.
  - issue frames from cited source passages.
  - interim-relief history and likelihood only under controlled predictive
    policy.
  - procedural-scrutiny / strictness / aggressiveness themes and scores only
    when backed by extracted passages, sample size, confidence band, source
    IDs, and limitations.
  - average disposal time only when calculated from reliable official data.
  - limitation note and evidence quality.
- Use `predictive_bench_strategy_enabled` as the initial tenant AI policy gate
  until a broader predictive-intelligence policy object replaces it.

DB models/migrations:

- Reuse:
  - `judge_decision_index`.
  - `judge_authority_affinity`.
  - `judge_statute_focus`.
  - `authority_citations`.
  - `authority_statute_references`.
  - `MatterCauseListEntry.judges_json`.
- Add only if needed:
  - `bench_forum_context_snapshots` for cached, source-linked responses.
  - `bench_forum_issue_extracts` if issue/ratio snippets need materialization.
- Avoid opaque aggregate "scores" columns. If a score is persisted, it must
  carry signal type, source IDs, sample size, confidence band, feature
  contributions, limitation note, policy gate, and audit link.

Frontend pages/components:

- Implemented in this slice:
  - Extend `/app/matters/[id]/predictive-intelligence` with a dense
    "Bench and judge context" section.
  - Show bench/court/forum scope, judge names, sample size, year window,
    observed signal distribution, confidence band, evidence quality, source
    links, missing-data state, and limitation copy.
- Future:
  - Update `BenchStrategyPanel` naming/copy to "Bench/forum intelligence".
  - Add standalone matter cockpit panel with:
    - evidence quality.
    - sample size.
    - cited sources.
    - limitation note.
    - top authorities/statutes.
    - issue frames.
    - source links.
    - predictive mode badge only when tenant policy enables it.
    - human-review state.

AI prompts/providers:

- Use retrieval plus structured summarization.
- Prompt must produce:
  - source-backed observations.
  - cited snippets.
  - limitations.
  - controlled predictive summaries only from supplied evidence fields.
- Structural tests must reject unsupported prediction, missing source IDs,
  missing sample size, missing confidence band, and missing disclaimer.

Source-data rules:

- Only official/licensed public-law sources.
- Bench/forum claims require sample size and source list.
- Weak coverage degrades to `insufficient_evidence`.
- No NJDG-derived judge/bench claim unless NJDG access and granularity are
  verified.

Tests:

- FT-LI-011, FT-LI-012.
- SEC-LI-001, SEC-LI-002, SEC-LI-003, SEC-LI-004.
- Existing no-favorability tests must be replaced or narrowed so they reject
  unsupported labels, not controlled predictive outputs with required evidence.

Security/tenant isolation checks:

- Matter endpoint enforces matter access.
- Public-law evidence is global, but query context and any matter facts are
  tenant-private.
- No tenant-private source appears in public judge/court profile unless it is
  explicitly a matter-scoped view for an authorized tenant member.
- Audit every generation/read if it consumes matter facts.

Acceptance criteria:

- A lawyer can see "in indexed decisions provided, this bench/forum addressed
  X with these citations" and click every source.
- Any favorability, likelihood, strictness/aggressiveness, settlement, or risk
  output has source IDs, sample size, confidence band, feature explanation,
  limitation note, human-review state, tenant-policy gate, and disclaimer.
- Weak evidence returns `insufficient_evidence`.

### LI-S6: Litigation Intelligence Integration Polish and Review Workflow

Status:

- Implemented and verified as LI-S6 V1. It is a read-only aggregation and
  review workflow layer over existing LI-S1/S2/S3/S5/S7 records.
- No accept/reject/edit mutation endpoint was implemented in LI-S6 V1; LI-S9
  adds that closure slice. Graph materialization, new prediction engines,
  corpus ingest, scraping, embedding, and backfill remain outside LI-S6.

Purpose:

- Tie LI-S1 proceeding signals, LI-S2 affidavit preparation, LI-S3 mock-hearing
  feedback, LI-S5 bench context, and LI-S7 predictive limitations into one
  matter-scoped human-review queue.
- Preserve source lineage and safe review copy without adding a new prediction
  engine, corpus ingestion job, or broad graph materialization.

User stories:

- US-LI-013.
- US-LI-010.

API/backend changes:

- Add read-only aggregation service:
  - `apps/api/src/caseops_api/services/litigation_intelligence_review.py`.
- Add API:
  - `GET /api/matters/{matter_id}/litigation-intelligence/review`.
- Returned review items must include closed item/source types, status, priority,
  confidence/evidence quality where available, sample size where available,
  limitation note, review reason, source ID, source snippet, and generated time.
- Unsupported item/source types fail schema validation and must not be routed by
  the frontend.
- Viewing the review queue writes `litigation_intelligence_review.viewed`.

DB models/migrations:

- No new persistence table for V1. LI-S6 reads existing source-backed tables:
  - `matter_proceeding_signals`.
  - `affidavit_statements`.
  - `affidavit_questions`.
  - `mock_hearing_sessions`.
  - `mock_hearing_responses`.
  - `predictive_signal_runs`.
  - `predictive_signal_items`.
  - `predictive_signal_evidence`.
- Source-linked graph tables remain deferred until a later legal-graph slice.

Frontend pages/components:

- Add matter cockpit page:
  - `/app/matters/{matter_id}/litigation-intelligence`.
  - Nav label: `Intelligence Review`.
- Render grouped review items, summary counts, source links, source snippets,
  limitation notes, review-required states, loading/error/empty states, and the
  disclaimer "decision support, not legal advice."
- Frontend must route only known source types to existing matter pages:
  timeline, documents, hearings, and predictive intelligence.

AI prompts/providers:

- No new AI prompt/provider in LI-S6. It reuses persisted outputs from earlier
  slices and does not generate new predictions or recommendations.

Source-data rules:

- Every review item is matter-scoped and source-linked.
- Predictive and bench-context items must remain source-backed decision support
  with sample size/confidence/evidence where supplied by LI-S5/LI-S7.
- No corpus ingest, scraping, embedding, or backfill is part of LI-S6.

Tests:

- FT-LI-018, FT-LI-019.
- SEC-LI-001, SEC-LI-002, SEC-LI-003, SEC-LI-004.

Security/tenant isolation checks:

- Review route enforces matter access, restricted matters, team scoping,
  ethical walls, and cross-tenant denial.
- Review items are read from tenant/matter-scoped records; public authority
  evidence can appear only through existing source-backed predictive lineage.
- No frontend-only trust: backend access checks remain authoritative.

Acceptance criteria:

- A lawyer can inspect one matter-level review queue for pending LI-S1/S2/S3
  and LI-S5/S7 limitations, with source snippets and source links.
- Every item has a closed source type and source ID.
- UI and API copy state decision support, not legal advice, and avoid
  guaranteed-outcome, judge-reputation, voice, emotion, biometric,
  psychological, or mental-health scoring language.
- Legal knowledge graph exploration beyond the LI-S11 matter graph foundation
  remains deferred.

### LI-S7: Predictive Litigation Intelligence Foundation

Purpose:

- Build the controlled predictive intelligence foundation required for judge,
  bench, forum, matter-risk, settlement, and hearing-prep score surfaces.
- LI-S7 does not approve opaque prediction. It approves explainable,
  source-backed, confidence-banded, tenant-gated decision support.

User stories:

- US-LI-007.
- US-LI-011.
- US-LI-012.
- US-LI-010.

API/backend changes:

- Add `GET /api/matters/{matter_id}/predictive-intelligence`.
- Add typed response contracts:
  - `PredictiveSignal`.
  - `PredictiveEvidence`.
  - `PredictionConfidence`.
  - `PredictionFeatureContribution`.
  - `BenchPredictiveSummary`.
  - `MatterRiskSummary`.
  - `HearingPrepScorecard`.
- Current implementation status:
  - LI-S7A is implemented and verified for typed schemas, route/service
    foundation, tenant policy gate, matter access enforcement, audit, and
    `insufficient_evidence` fallback.
  - LI-S7B is implemented and verified for source-bound outcome
    classification, official/licensed source allowlist enforcement, aggregate
    snapshots, backfill CLI, LLM quarantine/ModelRun behavior, and stale
    aggregate cleanup.
  - LI-S7C is implemented and verified for the matter cockpit Predictive
    Intelligence UI, strict frontend API parsing, disclaimer rendering,
    source-link rendering, disabled state, and insufficient-evidence state.
  - LI-S10 is implemented for calibrated signals exposed from existing LI-S7B
    aggregate snapshots. Broader source-family coverage and production rollout
    hardening remain future work, but not as a missing LI-S10 V1 requirement.
- Every output must keep source IDs, sample size, confidence band, features,
  limitations, human-review state, policy gate, audit contract, and the
  "decision support, not legal advice" disclaimer.

Predictive surfaces covered:

- Judge/bench/forum outcome tendency analytics.
- Interim relief likelihood.
- Notice issuance likelihood.
- Adjournment likelihood.
- Stay/interim order frequency.
- Disposal/delay risk.
- Matter risk score.
- Settlement inclination signal.
- Mock-hearing performance scoring.

DB models/migrations:

- Add `predictive_signal_runs`:
  - `id`, `company_id`, `matter_id`, `actor_membership_id`, `status`, `mode`,
    `sample_size`, `evidence_quality`, `disclaimer`, `limitation_note`,
    timestamps.
- Add `predictive_signal_items`:
  - `id`, `run_id`, `company_id`, `matter_id`, `signal_type`, `status`,
    `label`, `estimate_label`, `sample_size`, `confidence_label`,
    `confidence_band_low`, `confidence_band_high`, `limitation_note`,
    `features_json`, `missing_data_json`, timestamps.
- Add `predictive_signal_evidence`:
  - `id`, `run_id`, `item_id`, `company_id`, `matter_id`, `source_type`,
    `source_id`, `title`, `source_reference`, `excerpt`, `weight`,
    `source_date`, timestamps.
- Add `predictive_outcome_classifications` and
  `predictive_outcome_aggregate_snapshots` for LI-S7B source-bound
  classifications and aggregate snapshots.

Frontend pages/components:

- LI-S7C adds `/app/matters/[id]/predictive-intelligence`.
- Matter cockpit nav includes "Predictive Intelligence".
- The screen shows evidence quality, signal status, generated timestamp,
  policy state, confidence band, sample size, source links, limitations,
  disclaimer, matter-risk summary when available, hearing-prep scorecard when
  available, and `insufficient_evidence`/disabled states.

AI prompts/providers:

- LI-S7A must not ask an LLM to guess probabilities.
- LI-S7B LLM use, when explicitly enabled, is limited to classifying cited
  source text into approved labels and extracting rationale snippets.
- Every LLM/model use writes `ModelRun`; deterministic read-only aggregation
  writes predictive signal run rows and audit.
- LLMs must not invent probabilities; aggregate confidence is derived from
  sample size and label consistency.

Source-data rules:

- Official/licensed public-law sources only.
- Tenant-private matter facts remain matter-scoped.
- No eCourts/NJDG/API assumption until verified.
- No predictive signal may render as supported without evidence source IDs.
- Weak evidence returns `insufficient_evidence`.

Tests:

- FT-LI-012, FT-LI-015, FT-LI-016, FT-LI-017.
- NFT-LI-007.
- SEC-LI-001, SEC-LI-002, SEC-LI-003, SEC-LI-009, SEC-LI-010.
- Backend tests must cover tenant isolation, ethical walls, policy disabled,
  weak evidence fallback, strong fixture evidence, audit event, evidence IDs,
  no unsupported "judge is favorable" string, and observable hearing metrics.

Security/tenant isolation checks:

- Load matters through existing matter access checks.
- Tenant policy disabled blocks predictive output.
- Every predictive run is company/matter scoped.
- Every supported signal carries evidence IDs and can be audited back to source
  records.
- No cross-tenant matter data can enter public-law or bench/forum aggregates.

Acceptance criteria:

- `GET /api/matters/{matter_id}/predictive-intelligence` returns 403 or
  disabled state when tenant policy is off.
- With weak evidence, every predictive surface degrades to
  `insufficient_evidence` with missing-data requirements.
- With fixture evidence, at least one supported signal returns source IDs,
  sample size, confidence band, feature contributions, limitation note, human
  review flag, and disclaimer.
- Audit and predictive run records are written.
- Outcome classification/backfill and matter cockpit UI are implemented in
  LI-S7B/C.
- No voice, emotion, biometric, medical, or psychological scoring is
  implemented in LI-S7A/B/C.

### LI-S8: Final PRD Alignment, Release Readiness, and Gap Ledger

Status:

- Implemented as a docs/status/test-matrix alignment slice after LI-S1 through
  LI-S7 reached their scoped V1/foundation readiness.

Purpose:

- Align the Litigation Intelligence PRD with repo truth for LI-S1 through
  LI-S7.
- Record that no new product feature, prediction engine, graph materialization,
  corpus ingest, scraping, embedding, or backfill is part of LI-S8.
- Confirm whether the LI track exposes enterprise, security, or operational
  gaps that require `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md` updates.

Backend/API/DB/frontend changes:

- None. LI-S8 is documentation, status, and verification only.

Source-data and AI policy:

- Existing caveats remain binding:
  - outputs are source-backed decision support, not legal advice.
  - predictive surfaces require sample size, confidence band, source evidence,
    feature explanation, limitation note, tenant policy gate, and audit.
  - no broad voice/audio analysis, audio recording, speech analysis, emotion,
    biometric, psychological, mental-health, or voice-stress scoring is
    implemented.
  - no broad district/session/tribunal scraping or corpus ingest/backfill/
    embedding job is part of LI-S1 through LI-S13 feature work.
  - LI-S9 review mutations exist for the matter review queue; broader
    assignment/escalation workflows remain pending.
  - broad ingestion beyond LI-S12 readiness/proof tooling remains deferred
    where marked below.

Tests:

- Verify the LI targeted backend and frontend suites:
  - proceeding intelligence.
  - affidavit intelligence.
  - mock hearing.
  - legal source registry.
  - predictive intelligence and predictive outcomes.
  - litigation intelligence review.
  - migration order.
  - matter hearings/documents/predictive-intelligence/litigation-intelligence
    page tests.
  - MatterCockpitNav tests.

Acceptance criteria:

- No stale `Missing` or planned-only status remains for implemented LI-S1
  through LI-S7 slices.
- No PRD section claims deferred items are implemented.
- PRD caveats match current source-backed, tenant-scoped, human-reviewed
  implementation boundaries.
- Gap ledger is updated only if this pass finds a broader enterprise/security/
  ops gap.

### LI-S9: Review Mutations for Litigation Intelligence Queue

Status:

- Implemented as the first Litigation Intelligence Closure Track slice.
- Scope is limited to review mutations for existing source-backed LI-S6 queue
  items; it does not add new predictions, graph materialization, corpus ingest,
  scraping, embeddings, or voice/audio features.

Purpose:

- Let a litigation partner perform human-review actions on matter-scoped LI
  queue items without leaving the matter cockpit.
- Preserve source lineage, tenant isolation, and auditability for every queue
  mutation.

User stories:

- US-LI-013.
- US-028.
- US-040.

API/backend changes:

- Add `POST /api/matters/{matter_id}/litigation-intelligence/review/actions`.
- Allowed actions are closed:
  - `mark_reviewed`.
  - `accept`.
  - `reject`.
  - `edit_note`.
- Request contract requires a closed `item_type`, queue `item_id`, action, and
  optional note.
- Mutation service validates item ID prefix against item type, loads the source
  record in the same company/matter, and fails closed for unknown or mismatched
  items.
- Repeated terminal actions are idempotent: the resulting state remains
  `reviewed` and the request is audited with before/after state.

DB models/migrations:

- Add `litigation_intelligence_review_actions` via
  `20260512_0001_litigation_intelligence_review_actions.py`.
- Columns include `company_id`, `matter_id`, closed `item_type`, queue
  `item_id`, source type/id, action, note, before/after status,
  actor membership, and timestamp.
- Source records remain authoritative. Where a source table already has
  `review_status`, LI-S9 marks terminal actions as `reviewed`; predictive and
  bench-context items use the action ledger overlay.

Frontend pages/components:

- Extend `/app/matters/{matter_id}/litigation-intelligence` rows with:
  - reviewer note editor.
  - `Save note`.
  - `Mark reviewed`.
  - `Accept`.
  - `Reject`.
- Actions invalidate and reload the matter-scoped review queue.
- UI copy remains dense, professional, source-linked, and explicitly
  decision-support oriented.

AI prompts/providers:

- None. LI-S9 does not invoke an LLM or model.

Source-data rules:

- Mutations apply only to existing source-backed LI-S1/S2/S3/S5/S7 queue
  items.
- Unknown item or source types fail validation.
- Review actions do not create new predictions, recommendations, or legal
  advice.

Tests:

- Backend tests cover mark-reviewed, accept, reject, edit-note, idempotent
  repeated action, audit before/after metadata, closed item validation,
  cross-tenant denial, restricted matter denial, team-scoped denial, and ethical
  wall denial.
- Frontend tests cover action rendering and strict mutation payloads.

Security/tenant isolation checks:

- Route enforces review capability plus existing matter access checks,
  restricted matters, team scoping, ethical walls, and cross-tenant denial.
- Every mutation is company/matter scoped and audited with source identity and
  before/after state.

Acceptance criteria:

- A reviewer can mark a proceeding/affidavit/mock-hearing/predictive/bench
  queue item reviewed, accepted, rejected, or annotate it with a note.
- Repeating the same terminal action is safe and does not duplicate source
  state changes.
- The queue never mutates unknown item/source types.

### LI-S10: Calibrated Predictive Expansion

Status: Implemented.

Purpose:

- Expand controlled predictive analytics beyond LI-S7A/B/C foundations into
  calibrated, source-backed outcome/favorability/risk surfaces.

Required policy:

- Every output must include sample size, confidence band, source evidence,
  feature explanation, limitation note, tenant policy gate, audit trail, and
  "decision support, not legal advice."
- No LLM-only probability, win/loss claim, uncited judge reputation, or opaque
  favorability score is allowed.
- Weak evidence must degrade to `insufficient_evidence`.

Candidate surfaces:

- Bench/forum outcome tendency.
- Interim relief, notice issuance, stay/interim order, adjournment, disposal
  delay, adverse-order, settlement-inclination, and matter-risk analytics.

Implemented scope:

- `GET /api/matters/{matter_id}/predictive-intelligence` now returns
  `calibrated_signals` as an additive field backed by existing LI-S7B
  `predictive_outcome_aggregate_snapshots`.
- Each calibrated signal exposes signal type, scope, sample size, observed
  source-label distribution/rate, Wilson confidence band, calibration level,
  evidence quality, source evidence links, limitation note, aggregate snapshot
  reference, generated timestamp, and the decision-support disclaimer.
- Weak sample size, unsupported snapshot status, or missing evidence IDs
  degrades to `insufficient_evidence` or `limited_context`; no probability is
  shown from LLM intuition.
- `/app/matters/[id]/predictive-intelligence` renders a compact calibrated
  signal table with source links, confidence band, sample size, observed
  historical pattern copy, limitation notes, and safe insufficient-evidence
  states.

Deferred beyond LI-S10:

- No new prediction engine, LLM summarization path, corpus ingest/backfill,
  embedding job, graph materialization, or external source scraping is part of
  LI-S10.

### LI-S11: Legal Knowledge Graph Materialization

Status: Implemented foundation.

Purpose:

- Materialize source-linked legal relationships across entities, issues,
  statutes, orders, affidavits, judges, forums, outcomes, and matter events.

Required policy:

- Every edge must carry provenance, source ID, extraction method, confidence,
  tenant/matter scope where applicable, and refresh metadata.
- Graph refresh must be idempotent and auditable.
- UI exploration beyond the matter cockpit foundation is a later sub-slice after
  graph lineage and access checks are verified.

Implemented scope:

- `legal_knowledge_graph_runs`, `legal_knowledge_graph_nodes`, and
  `legal_knowledge_graph_edges` materialize a single-matter, tenant-scoped
  graph from existing source-backed LI records.
- `GET /api/matters/{matter_id}/legal-knowledge-graph` returns the current
  graph with closed node, edge, and source contracts.
- `POST /api/matters/{matter_id}/legal-knowledge-graph/materialize` rebuilds
  the graph idempotently for that matter and audits the mutation.
- The foundation consumes existing LI-S1 proceeding signals, LI-S2 affidavit
  statements/questions, LI-S3 mock-hearing questions/responses, LI-S5/LI-S7
  predictive/bench evidence rows, and LI-S9 review-action metadata only.
- `/app/matters/[id]/knowledge-graph` renders a compact node/relationship table
  with source snippets, source links, filters, empty/loading/error states, and
  the decision-support disclaimer.

Deferred beyond LI-S11:

- No external corpus graphing, corpus ingest/backfill, embedding job,
  graph-wide analytics engine, or broad visual graph explorer is implemented.
- No new prediction engine, LLM-only probability, voice/audio, emotion,
  biometric, psychological, or mental-health scoring is implemented.

### LI-S12: District/Session/Tribunal Source Expansion Plan and Safe Adapter Proofs

Status: Implemented foundation/proof layer.

Purpose:

- Move beyond LI-S4 registry visibility into explicit lawful-source readiness,
  adapter-contract proof gates, and per-source caveats for district courts,
  session courts, tribunals, consumer forums, bare acts, and arbitration
  forums.

Required policy:

- Lawful official/licensed adapters only.
- No captcha/session-gated scraping.
- Source registry readiness must mark each source as ingest-ready, planned,
  blocked, manual-only, official, licensed, or test/internal.
- Each source family needs lineage proof, parser quality checks, HNSW retrieval
  quality evidence where embedded, and per-source rollback/backfill controls.

Implemented scope:

- `services/authority_sources.py` now exposes explicit source readiness states:
  `ingest_ready`, `proof_required`, `blocked_captcha_or_session`,
  `blocked_license_or_unknown`, and `manual_or_partner_only`.
- Source readiness output includes source key/name, category, jurisdiction,
  court/forum, access mode, official/licensed/manual/test/unlicensed source
  type, captcha/session-gated posture, adapter availability, public corpus
  allowance, predictive aggregate allowance, proof status, blocked reason,
  lineage requirements, and caveats.
- `assert_source_adapter_ingest_ready` is the proof gate for adapter use. It
  fails closed for unknown, manual, unlicensed, captcha/session-gated, or
  proof-required sources.
- Existing Supreme Court and High Court official adapter-backed sources remain
  ingest-ready. eCourts district/session sources remain blocked because the
  available surfaces are captcha/session gated.
- Tribunal, consumer forum, statutory bare-act, and arbitration entries appear
  in readiness output but are not public-corpus or predictive-aggregate ready
  until lawful adapter access, parser proof, and source-quality gates exist.
- Bare-act/statute sources are represented separately from judgment/order
  sources and are never eligible for predictive outcome aggregates by default.

Deferred beyond LI-S12:

- No broad district/session/tribunal ingestion, public corpus backfill,
  embedding job, source scraping, paid-source pull, or predictive expansion is
  implemented.
- No source is promoted from readiness/proof-required to ingest-ready without
  lawful access, adapter contract proof, lineage proof, and the corpus quality
  gate.

### LI-S13: Hearing Performance Coach

Status: Implemented transcript-first foundation.

Purpose:

- Extend text-first mock hearing preparation into a consented performance coach
  using existing typed mock-hearing responses and source-backed LI-S2 question
  banks.

Required policy:

- Voice/audio features require tenant opt-in and explicit participant consent.
- Transcript-first metrics are required before any audio-derived metrics.
- Allowed metrics must be observable performance markers, such as answer
  completeness, consistency with affidavit, unsupported assertions, document
  references, and response timing.
- Retention policy, deletion controls, and audit must be explicit.
- No medical, mental-health, psychological, biometric, credibility, stress, or
  emotion diagnosis is allowed.

Implemented scope:

- `GET /api/matters/{matter_id}/hearing-coach` returns matter-scoped readiness,
  response count, consent-required state, limitation notes, and the training-aid
  disclaimer.
- `POST /api/matters/{matter_id}/mock-hearings/{session_id}/coach` generates a
  deterministic report only when the user acknowledges the transcript-first
  preparation gate.
- LI-S13 reuses existing `mock_hearing_sessions`, `mock_hearing_questions`, and
  `mock_hearing_responses`; no new table or migration is required for V1.
- Metrics are observable text markers only: answered question, source-reference
  use, unsupported assertions, contradictions, clarity/completeness scores,
  direct-answer marker, response length marker, and missing exhibit/reference
  marker.
- Every feedback item links back to the mock-hearing response, question, source
  affidavit question/statement, attachment/chunk where present, and bounded
  source quote.
- The service is deterministic and does not invoke an LLM or create `ModelRun`
  rows.
- Routes enforce tenant/matter access, restricted matter rules, team scoping,
  ethical walls, and cross-tenant denial through the existing matter access
  layer.
- `/app/matters/[id]/hearings` includes a compact Hearing coach section with
  consent acknowledgement, observable metrics, source links, safe disclaimer,
  and empty/loading/error states.

Deferred beyond LI-S13:

- No broad voice/audio analysis, recording workflow, speech analysis, emotion,
  biometric, psychological, mental-health, stress, lie-detection, or personality
  inference is implemented.
- Any future recording or transcript import workflow requires explicit tenant
  opt-in, participant consent, retention/deletion controls, audit, and a
  separate strict review.

## 9. Recommended Implementation Order

1. LI-S0: PRD and source policy.
2. LI-S1: Proceeding sheet intelligence (implemented and verified).
3. LI-S2: Affidavit hearing prep (implemented and verified).
4. LI-S3: Mock hearing simulator V1 (implemented and verified).
5. LI-S4: District/session/tribunal source framework foundation
   (implemented and verified).
6. LI-S5: Evidence-backed bench/forum intelligence (implemented and verified).
7. LI-S6: Litigation intelligence integration/review workflow read-only V1
   (implemented and verified).
8. LI-S7A: Predictive Intelligence Data Contract + API foundation
   (implemented and verified).
9. LI-S7B: Outcome-classification and signal backfill jobs (implemented and
   verified).
10. LI-S7C: Matter cockpit predictive UI (implemented and verified).
11. LI-S8: Final PRD alignment, release readiness, and gap ledger
    (implemented as docs/status verification).
12. LI-S9: Review mutations for Litigation Intelligence queue
    (implemented).
13. LI-S10: Calibrated predictive expansion (implemented).
14. LI-S11: Legal knowledge graph materialization foundation (implemented).
15. LI-S12: District/session/tribunal source expansion proof layer
    (implemented foundation; broad ingestion deferred).
16. LI-S13: Hearing performance coach transcript-first foundation
    (implemented).

Historical sequencing notes:

- LI-S2 could start while LI-S1 was in review because it mostly used existing
  document and drafting foundations.
- LI-S4 preceded LI-S5 so bench/forum context could rely on explicit source
  registry semantics.
- LI-S1 through LI-S7 are complete enough to leave the LI feature queue at
  their scoped V1/foundation boundaries after LI-S8 verification.
- LI-S10 should wait until LI-S4/LI-S5 source and context semantics are stable
  for any source family beyond current official/licensed corpus layers.

## 10. Prohibited Patterns and Closure Track

Prohibited patterns:

- Opaque or unsupported black-box judge favorability.
- Generic win/loss prediction without source IDs, sample size, confidence
  band, feature explanation, limitation note, policy gate, audit, and human
  review.
- LLM-only success probability or adverse-order probability.
- Likelihood surfaces for interim relief, adjournment, notice issuance, stay,
  or adverse order when evidence is below threshold.
- Strictness/aggressiveness scores without source passages, sample size,
  confidence band, and limitations.
- Settlement inclination scores without official/licensed source evidence.
- Unsupported legal risk scores.
- Medical, mental-health, emotional, psychological, biometric, credibility, or
  voice-stress diagnosis.
- Autonomous court filing or external legal action.
- Cross-tenant analytics over private matter data.
- Cross-tenant model training on customer data without explicit opt-in.
- Bypassing captcha/session restrictions on court or tribunal sites.
- Using unlicensed paid sources or third-party databases.

Closure slices, not abandonment:

- LI-S11 broad graph explorer and corpus-scale graph analytics beyond the
  matter-scoped foundation.
- Broad district/session/tribunal ingestion beyond LI-S12 safe adapter
  readiness/proof tooling.
- NJDG-based analytics until access, permitted use, and granularity are
  verified.
- Paid commentary integration.
- Client-portal sharing of prep reports.
- Auto-notification to clients from proceeding sheets.

## 11. LI Track Status Checklist

- [x] LI-S1 implemented and verified: proceeding/order-sheet intelligence over
      raw `MatterCourtOrder.order_text`, source-stable idempotency, anchored
      deadline task/deadline creation, matter access enforcement, audit, and
      hearings/timeline integration.
- [x] LI-S2 implemented and verified: affidavit intelligence over raw
      attachment chunks, source-quoted statements/questions, review-required
      states, matter access enforcement, audit, and documents page UI.
- [x] LI-S3 implemented and verified: text-only mock hearing simulator using
      LI-S2 question banks, deterministic/source-backed feedback, audit,
      idempotent completion, and hearings page UI.
- [x] LI-S4 implemented and verified: legal source registry/readiness
      foundation for official/licensed sources, blocked captcha/session-gated
      district/session records, planned tribunal/forum records, and predictive
      aggregate allowlist.
- [x] LI-S5 implemented and verified: additive bench context inside Predictive
      Intelligence with sample size, observed distribution, source evidence,
      confidence/evidence quality, and limitation notes.
- [x] LI-S6 implemented and verified: read-only matter Litigation Intelligence
      Review page/API over existing source-backed LI records, closed source
      contracts, safe copy, access enforcement, and audit.

- [x] LI-S7A implemented and verified: predictive data contract, route/service
      foundation, tenant policy gate, matter access enforcement, audit, and
      insufficient-evidence fallback.
- [x] LI-S7B implemented and verified: source-bound outcome classification,
      official/licensed source allowlist, aggregate snapshots, backfill CLI,
      LLM quarantine/ModelRun persistence, and stale aggregate cleanup.
- [x] LI-S7C implemented and verified: matter cockpit Predictive Intelligence
      page/nav, strict API parsing, professional decision-support UI,
      disclaimer, source links, disabled state, and insufficient-evidence state.
- [x] LI-S8 implemented: final PRD status alignment, caveat check, release
      readiness verification command plan, and gap-ledger review.
- [x] LI-S9 implemented: review queue mutation endpoint/UI actions for
      mark-reviewed, accept, reject, edit-note, idempotency, audit before/after
      state, and unsafe-access denial.
- [x] LI-S10 implemented: calibrated predictive expansion with source-backed
      aggregate snapshot signals, observed source-label distributions,
      confidence bands, sample size, limitation notes, and source evidence.
- [x] LI-S11 implemented: matter-scoped legal knowledge graph foundation with
      tenant-scoped runs, nodes, edges, source provenance, idempotent refresh,
      audit, closed contracts, and compact cockpit UI.
- [x] LI-S12 implemented: district/session/tribunal safe adapter readiness and
      proof layer with explicit source states, fail-closed adapter contract,
      blocked eCourts captcha/session posture, and no broad ingestion.
- [x] LI-S13 implemented: consent-gated transcript-first hearing coach
      foundation over typed mock-hearing responses, observable preparation
      metrics, source-linked feedback, audit, safe cockpit UI, and no
      medical/mental-health diagnosis.

## 12. Remaining Approval Checklist

- [ ] User picks the first source-family pilot for LI-S4:
      district/session court, NCLT/NCLAT, DRT/DRAT, ITAT, NGT, CAT, NCDRC, or
      manual-upload-only proceeding sheets.
- [ ] User confirms mock hearing V1 remains text/observable-metric only until a
      separate voice/audio policy and consent model is approved.
