export const marketingFaqs = [
  {
    q: "Is CaseOps another chatbot for lawyers?",
    a: "No. CaseOps is a system of work. Intake, matters, notices, drafting, hearing prep, research, contracts, compliance review, cause lists, and billing are first-class workspaces backed by a matter graph. AI is a feature of the system, not the product.",
  },
  {
    q: "How does CaseOps avoid hallucinated citations?",
    a: "Legal knowledge lives in retrieval and source systems, not the model. Every substantive answer is grounded in statutes, judgments, or your own precedents with inline citations, assumptions, missing facts, and confidence. Weak-evidence prompts return an explicit refusal. The structured statute model feeds available bare text into appeal drafts so quotations can be checked against the source.",
  },
  {
    q: "How do intake conflict checks work?",
    a: "A permitted user can run an optional pre-engagement scan against workspace clients and matters. Candidate overlaps stay pending until a partner or admin clears, marks conflicted, or explicitly waives them. The scan is review evidence, not a status gate: New Matter starts Active by default, and Intake or On hold can move to Active with no check or with any check result. After a party-scope change or reopen, run a fresh check before describing the matter as currently cleared.",
  },
  {
    q: "How are received and sent notices tracked?",
    a: "Each matter has a Notices workspace for received and sent notices. Received notices can track reply ownership, due dates, status, reply documents, and supporting files. When a reply is required and a due date is set, CaseOps links a matter deadline; uploading or recording the reply marks that deadline done.",
  },
  {
    q: "How does case tracking work?",
    a: "Production scheduled refresh starts at 6 PM IST for explicitly bookmarked cases and bounded batches of active matters with a reliable CNR or exact case-number-plus-court identity. It keeps backlog for the next run, batches fairly across tenants, and records attempted, refreshed, changed, skipped, blocked, provider-call, error, partial, and backlog metrics. CaseOps does not bypass captcha, login, or session-gated court sources.",
  },
  {
    q: "How does court-order compliance extraction work?",
    a: "Manual and adapter-created court orders first go through deterministic extraction. AI extraction runs only when tenant policy allows it, must pass schema validation, and creates source-backed review-required compliance items by default. Lawyers confirm, edit, reject, waive, complete, or retry items before tasks and deadlines become active unless a tenant admin has explicitly enabled auto-activation.",
  },
  {
    q: "How cautious are deadline calculations?",
    a: "Deadline items show source snippet, confidence, and the calculation convention. Calendar days are the default unless a configured court calendar exists. Ambiguous phrases such as from today, within two weeks, next date, or missing order date remain review-required. CaseOps does not invent due dates.",
  },
  {
    q: "What is included in matter billing?",
    a: "Matter billing is separate from CaseOps SaaS subscription billing. Tenant admins configure law-firm profiles, firm GSTIN/PAN/name/address, client billing fields, place of supply, SAC/HSN or service classification, invoice sequence, payment terms, hourly and fixed-fee arrangements, milestones, expenses, retainers or advances, GST split, TDS adjustments, amount paid/outstanding, and server-rendered invoice PDFs.",
  },
  {
    q: "Does the appeal draft consider which bench will hear it?",
    a: "Yes. When a matter has an upcoming listing whose bench is resolved against the judge catalog, the appeal-memorandum draft can pull authorities authored by that bench and prefer ones aligned with the matter's practice area. Predictive and bench-context surfaces stay source-backed: they show sample size, confidence band, evidence links, and limitation notes rather than uncited court-strategy claims.",
  },
  {
    q: "How is tenant data isolated?",
    a: "Every tenant-owned record, document, embedding, and audit event is filtered at the query and storage layer. Shared public authority records are deliberately separate from tenant-private data. Matter-level access restrictions override broad role access. Tenant-facing surfaces do not expose provider tokens, raw provider payloads, raw prompts, raw LLM responses, internal costs, or unauthorized tenant-private data.",
  },
  {
    q: "Can we self-host or run in a private VPC?",
    a: "Enterprise deployment is planned and readiness-scaffolded, but not marketed as live. Private VPC, on-prem inference, OIDC/SAML SSO, SCIM, and dedicated connectors require security review, provider/UAT evidence, and a separate implementation signoff.",
  },
  {
    q: "Who owns the data used to fine-tune models?",
    a: "You do. Customer data is not used for cross-tenant training by default. Tenant-specific model adaptation is planned and would require an explicit opt-in inside the tenant boundary.",
  },
] as const;
