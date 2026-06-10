import { vi } from "vitest";

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function downloadResponse(name: string, body = "row\n"): Response {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "text/csv",
      "content-disposition": `attachment; filename="${name}"`,
    },
  });
}

const price = (
  id: string,
  amount: number | null,
  interval: string,
  taxBehavior = "exclusive",
) => ({
  id,
  amount_minor: amount,
  currency: "INR",
  interval,
  tax_behavior: taxBehavior,
  tax_rate_bps: 1800,
});

export const planCatalog = {
  version: "2026.05.v1",
  plans: [
    {
      id: "plan-solo-core",
      plan_code: "solo_core",
      version: "2026.05.v1",
      segment: "solo",
      display_name: "Solo Core",
      description: "Entry plan for solo lawyers.",
      publicly_visible: true,
      trial_eligible: true,
      prices: [
        price("price-solo-core-m", 99900, "month", "inclusive"),
        price("price-solo-core-y", 999000, "year", "inclusive"),
      ],
      entitlements: {
        users_internal_limit: 2,
        matters_active_limit: 50,
        tracked_cases_limit: 50,
        ai_credits_monthly: 100,
        storage_bytes_limit: 2147483648,
        case_refresh_cadence: "weekday_daily",
      },
    },
    {
      id: "plan-solo-pro",
      plan_code: "solo_pro",
      version: "2026.05.v1",
      segment: "solo",
      display_name: "Solo Pro",
      description: "Hero solo plan.",
      publicly_visible: true,
      trial_eligible: true,
      prices: [
        price("price-solo-pro-m", 199900, "month", "inclusive"),
        price("price-solo-pro-y", 1999000, "year", "inclusive"),
      ],
      entitlements: {
        users_internal_limit: 4,
        matters_active_limit: 250,
        tracked_cases_limit: 200,
        ai_credits_monthly: 300,
        storage_bytes_limit: 10737418240,
        case_refresh_cadence: "daily",
      },
    },
    {
      id: "plan-firm-growth",
      plan_code: "firm_growth",
      version: "2026.05.v1",
      segment: "firm",
      display_name: "Firm Growth",
      description: "Hero firm plan.",
      publicly_visible: true,
      trial_eligible: true,
      prices: [
        price("price-firm-growth-m", 1999900, "month"),
        price("price-firm-growth-y", 20999000, "year"),
      ],
      entitlements: {
        users_internal_limit: 15,
        matters_active_limit: 1500,
        tracked_cases_limit: 1000,
        ai_credits_monthly: 1200,
        storage_bytes_limit: 161061273600,
        case_refresh_cadence: "smart_daily",
      },
    },
    {
      id: "plan-gc-professional",
      plan_code: "gc_professional",
      version: "2026.05.v1",
      segment: "gc",
      display_name: "GC Professional",
      description: "Corporate GC plan.",
      publicly_visible: true,
      trial_eligible: false,
      prices: [price("price-gc-prof-y", 80000000, "year")],
      entitlements: {
        users_internal_limit: 15,
        matters_active_limit: 10000,
        tracked_cases_limit: 25000,
        ai_credits_monthly: 30000,
        storage_bytes_limit: 1099511627776,
        case_refresh_cadence: "priority_daily",
      },
    },
  ],
  add_ons: [
    {
      id: "addon-ai-250",
      plan_code: "addon_ai_250",
      version: "2026.05.v1",
      segment: "addon",
      display_name: "AI credit pack 250",
      description: "250 credits, expires in 12 months.",
      publicly_visible: true,
      trial_eligible: false,
      prices: [price("price-ai-250", 119900, "one_time", "exclusive")],
      entitlements: { ai_credits_topup: 250 },
    },
    {
      id: "addon-cases-500",
      plan_code: "addon_cases_500",
      version: "2026.05.v1",
      segment: "addon",
      display_name: "Tracked case pack 500",
      description: "500 additional tracked cases.",
      publicly_visible: true,
      trial_eligible: false,
      prices: [price("price-cases-500", 249900, "month", "exclusive")],
      entitlements: { tracked_cases_limit: 500 },
    },
  ],
};

export const currentBilling = {
  billing_account: {
    id: "acct-1",
    company_id: "company-1",
    billing_email: "owner@example.com",
    billing_name: "Owner One",
    billing_phone: null,
    gstin: null,
    billing_address: null,
    tax_treatment: "gst_unregistered",
  },
  subscription: {
    id: "sub-1",
    plan_code: "solo_pro",
    plan_name: "Solo Pro",
    status: "active",
    segment: "solo",
    billing_interval: "month",
    current_period_start: "2026-05-01T00:00:00Z",
    current_period_end: "2026-06-01T00:00:00Z",
    trial_end: null,
    cancel_at_period_end: false,
    externally_billable: true,
    source: "self_service",
  },
  entitlements: {},
  usage: {
    ai_credits_included: 300,
    ai_credits_used: 75,
    ai_credits_remaining: 225,
    topup_credits_available: 250,
    tracked_cases_used: 40,
    tracked_cases_limit: 200,
    manual_refreshes_used_today: 2,
    manual_refreshes_limit_daily: 10,
    storage_used_bytes: 2147483648,
    storage_limit_bytes: 10737418240,
    users_internal_used: 2,
    users_internal_limit: 4,
    users_viewer_used: 0,
    users_viewer_limit: 0,
    matters_active_used: 12,
    matters_active_limit: 250,
  },
  payment_provider: {
    mode: "disabled",
    ready: false,
  },
};

export const checkoutResponse = {
  id: "chk-1",
  checkout_type: "new_subscription",
  status: "provider_disabled",
  amount_minor: 199900,
  tax_amount_minor: 0,
  total_amount_minor: 199900,
  currency: "INR",
  provider: "pine_labs_plural",
  provider_checkout_url: null,
  provider_order_id: "mock-order-1",
  provider_disabled: true,
  next_action: "provider_disabled",
  created_at: "2026-05-31T00:00:00Z",
  expires_at: "2026-05-31T01:00:00Z",
};

export const invoices = {
  invoices: [
    {
      id: "inv-1",
      invoice_number: "SAAS-001",
      invoice_type: "manual",
      amount_minor: 100000,
      tax_amount_minor: 18000,
      total_amount_minor: 118000,
      amount_received_minor: 118000,
      currency: "INR",
      status: "paid",
      issued_on: "2026-05-31",
      due_on: "2026-06-07",
      paid_on: "2026-05-31",
    },
  ],
};

export const creditLedger = {
  rows: [
    {
      id: "ledger-1",
      credit_bucket: "included",
      event_type: "grant",
      delta: 300,
      balance_after: 300,
      reason: "Monthly plan grant",
      source_object_type: "subscription",
      source_object_id: "sub-1",
      expires_at: null,
      created_at: "2026-05-31T00:00:00Z",
    },
  ],
};

export const usageReport = {
  period_start: "2026-05-01T00:00:00Z",
  period_end: "2026-06-01T00:00:00Z",
  snapshot: currentBilling.usage,
  by_feature: [{ key: "matter_recommendation", label: "Matter recommendation", quantity: 3, credits: 3 }],
  by_user: [{ key: "user-1", label: "Owner One", quantity: 3, credits: 3 }],
  by_matter: [{ key: "matter-1", label: "EXT-001", quantity: 2, credits: 2 }],
  by_tracked_case: [{ key: "cnr-1", label: "CNR123", quantity: 1, credits: 0 }],
  daily: [{ key: "2026-05-31", label: "2026-05-31", quantity: 3, credits: 3 }],
  blocked_events: [{ key: "ai_credit_exhausted", label: "AI credit exhausted", quantity: 1, credits: 0 }],
};

export const platformOverview = {
  mrr_minor: 5000000,
  arr_minor: 60000000,
  active_subscriptions: 12,
  trial_count: 3,
  failed_payments: 1,
  gross_revenue_minor: 12000000,
  recognized_revenue_minor: 10000000,
  total_variable_cost_minor: 2000000,
  gross_profit_minor: 8000000,
  gross_margin_bps: 8000,
  margin_alerts: [
    {
      company_id: "company-1",
      company_name: "Acme Law",
      message: "Stress-case margin below guardrail.",
    },
  ],
};

export const enrollments = {
  enrollments: [
    {
      id: "enroll-1",
      company_id: "company-1",
      contact_name: "Owner One",
      contact_email: "owner@example.com",
      company_name: "Acme Law",
      segment: "firm",
      selected_plan: "firm_growth",
      status: "trial_started",
      created_at: "2026-05-31T00:00:00Z",
    },
  ],
};

export const profitRows = {
  rows: [
    {
      company_id: "company-1",
      company_name: "Acme Law",
      period_start: "2026-05-01T00:00:00Z",
      period_end: "2026-06-01T00:00:00Z",
      gross_revenue_minor: 12000000,
      recognized_revenue_minor: 10000000,
      tax_minor: 1800000,
      discounts_minor: 0,
      payment_provider_cost_minor: 120000,
      llm_cost_minor: 400000,
      storage_cost_minor: 25000,
      case_refresh_cost_minor: 75000,
      total_variable_cost_minor: 620000,
      gross_profit_minor: 9380000,
      gross_margin_bps: 9380,
      status: "ok",
    },
  ],
};

export const companyProfitability = {
  companies: profitRows.rows,
};

export const providerEvents = {
  events: [
    {
      id: "evt-1",
      provider: "pine_labs_plural",
      provider_event_id: "pl_evt_1",
      event_type: "ORDER_PROCESSED",
      processing_status: "processed",
      provider_order_id: "order-1",
      company_id: "company-1",
      received_at: "2026-05-31T00:00:00Z",
      processed_at: "2026-05-31T00:00:01Z",
      error_message: null,
    },
  ],
};

export const tenantIntegrations = {
  connectors: [
    {
      key: "google_calendar",
      name: "Google Calendar",
      category: "calendar",
      provider: "google_calendar",
      status: "blocked",
      enabled: true,
      configured: false,
      blocked: true,
      healthy: false,
      degraded: false,
      last_success: null,
      last_failure: null,
      next_run: null,
      webhook_status: "not_configured",
      token_expiry: null,
      required_config_names: [
        "GOOGLE_CALENDAR_CLIENT_ID",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_CALENDAR_REDIRECT_URI",
      ],
      scopes: [
        "https://www.googleapis.com/auth/calendar.events",
      ],
      runbook_link: "docs/runbooks/provider-operations-readiness-2026-06-02.md",
      provider_operations_link: "/app/admin/provider-operations",
    },
    {
      key: "gmail",
      name: "Gmail",
      category: "email",
      provider: "gmail",
      status: "blocked",
      enabled: true,
      configured: false,
      blocked: true,
      healthy: false,
      degraded: false,
      last_success: null,
      last_failure: null,
      next_run: null,
      webhook_status: "missing",
      token_expiry: null,
      required_config_names: [
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REDIRECT_URI",
        "GMAIL_PUBSUB_TOPIC",
        "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
      ],
      scopes: [
        "https://www.googleapis.com/auth/gmail.metadata",
      ],
      runbook_link: "docs/runbooks/provider-operations-readiness-2026-06-02.md",
      provider_operations_link: "/app/admin/provider-operations",
    },
    {
      key: "google_drive",
      name: "Google Drive",
      category: "documents",
      provider: "google_drive",
      status: "healthy",
      enabled: true,
      configured: true,
      blocked: false,
      healthy: true,
      degraded: false,
      last_success: null,
      last_failure: null,
      next_run: null,
      webhook_status: "disabled",
      token_expiry: null,
      required_config_names: [
        "GOOGLE_DRIVE_CLIENT_ID",
        "GOOGLE_DRIVE_CLIENT_SECRET",
        "GOOGLE_DRIVE_REDIRECT_URI",
      ],
      scopes: [
        "https://www.googleapis.com/auth/drive.readonly",
      ],
      runbook_link: "docs/runbooks/provider-operations-readiness-2026-06-02.md",
      provider_operations_link: "/app/admin/provider-operations",
    },
    {
      key: "pine_labs",
      name: "Pine Labs Plural",
      category: "payments",
      provider: "pine_labs_plural",
      status: "disabled",
      enabled: false,
      configured: false,
      blocked: true,
      healthy: false,
      degraded: false,
      last_success: null,
      last_failure: null,
      next_run: null,
      webhook_status: "missing",
      token_expiry: null,
      required_config_names: ["PINE_LABS_API_BASE_URL", "PINE_LABS_WEBHOOK_SECRET"],
      scopes: [],
      runbook_link: "docs/runbooks/pine-labs-uat-readiness-2026-06-02.md",
      provider_operations_link: "/app/admin/billing",
    },
    {
      key: "sendgrid",
      name: "SendGrid",
      category: "email",
      provider: "sendgrid",
      status: "blocked",
      enabled: false,
      configured: false,
      blocked: true,
      healthy: false,
      degraded: false,
      last_success: null,
      last_failure: null,
      next_run: null,
      webhook_status: "missing",
      token_expiry: null,
      required_config_names: ["SENDGRID_API_KEY", "SENDGRID_WEBHOOK_PUBLIC_KEY"],
      scopes: [],
      runbook_link: "docs/runbooks/provider-operations-readiness-2026-06-02.md",
      provider_operations_link: "/app/admin/provider-operations",
    },
  ],
};

export const tenantIntegrationHealth = {
  health: [
    {
      id: "health-gmail",
      company_id: "company-1",
      provider: "gmail",
      configured_state: "missing_config",
      connected_state: "missing_config",
      last_success_at: null,
      last_failure_at: "2026-06-10T00:00:00Z",
      error_category: "missing_config",
      required_scopes: ["https://www.googleapis.com/auth/gmail.metadata"],
      granted_scopes: [],
      missing_scopes: ["https://www.googleapis.com/auth/gmail.metadata"],
      token_expires_at: null,
      token_refresh_status: "not_available",
      webhook_status: "missing",
      polling_status: "ready",
      rate_limit_status: "ok",
      next_retry_at: null,
      disabled_reason: null,
      last_checked_at: "2026-06-10T00:00:00Z",
      operational_alerts: ["missing_config"],
      setup_actions: ["Configure Gmail OAuth"],
      provider_operations_link: "/app/admin/provider-operations",
      created_at: "2026-06-10T00:00:00Z",
      updated_at: "2026-06-10T00:00:00Z",
    },
    {
      id: "health-drive",
      company_id: "company-1",
      provider: "google_drive",
      configured_state: "configured",
      connected_state: "connected",
      last_success_at: "2026-06-10T00:00:00Z",
      last_failure_at: null,
      error_category: null,
      required_scopes: ["https://www.googleapis.com/auth/drive.readonly"],
      granted_scopes: ["https://www.googleapis.com/auth/drive.readonly"],
      missing_scopes: [],
      token_expires_at: null,
      token_refresh_status: "refresh_available",
      webhook_status: "disabled",
      polling_status: "ready",
      rate_limit_status: "ok",
      next_retry_at: null,
      disabled_reason: null,
      last_checked_at: "2026-06-10T00:00:00Z",
      operational_alerts: [],
      setup_actions: [],
      provider_operations_link: "/app/admin/provider-operations",
      created_at: "2026-06-10T00:00:00Z",
      updated_at: "2026-06-10T00:00:00Z",
    },
  ],
};

export const platformIntegrations = {
  connectors: tenantIntegrations.connectors.map((connector) => ({
    ...connector,
    internal_cost_label:
      connector.key === "pine_labs" ? "payment MDR/fixed-fee" : "email delivery unit cost",
    risk_label:
      connector.key === "pine_labs" ? "production payments disabled" : "webhook risk",
    platform_notes:
      connector.key === "pine_labs"
        ? ["Do not enable live payments until founder UAT go/no-go."]
        : ["Webhook events must remain signature verified."],
  })),
};

export const platformIntegrationHealth = {
  health: tenantIntegrationHealth.health,
};

export const googleDriveStatus = {
  provider: "google_drive",
  configured: true,
  missing_config_names: [],
  connections: [
    {
      id: "drive-conn-1",
      company_id: "company-1",
      membership_id: "membership-1",
      provider: "google_drive",
      provider_account_id: "drive-account-1",
      display_email: "owner@example.com",
      status: "connected",
      scopes: ["https://www.googleapis.com/auth/drive.readonly"],
      connected_at: "2026-06-08T00:00:00Z",
      last_list_at: null,
      created_at: "2026-06-08T00:00:00Z",
      updated_at: "2026-06-08T00:00:00Z",
    },
  ],
};

export const googleDriveFiles = {
  provider: "google_drive",
  connection_id: "drive-conn-1",
  files: [
    {
      provider_file_id: "drive-file-1",
      name: "Signed vakalatnama.pdf",
      mime_type: "application/pdf",
      size_bytes: 2048,
      modified_time: "2026-06-08T00:00:00Z",
      web_url: null,
    },
  ],
};

export const googleWorkspaceConfiguration = {
  provider: "google_workspace",
  configured: true,
  config_source: "tenant_admin",
  enabled: true,
  calendar_enabled: true,
  gmail_enabled: true,
  drive_enabled: true,
  required_config: [
    { name: "GOOGLE_WORKSPACE_CLIENT_ID", configured: true },
    { name: "GOOGLE_WORKSPACE_CLIENT_SECRET", configured: true },
    { name: "GOOGLE_CALENDAR_REDIRECT_URI", configured: true },
    { name: "GMAIL_REDIRECT_URI", configured: true },
    { name: "GOOGLE_DRIVE_REDIRECT_URI", configured: true },
  ],
  required_approvals: [
    {
      key: "oauth_consent_model_approved",
      label: "Google Workspace OAuth consent approved",
      approved: true,
    },
    {
      key: "scopes_approved",
      label: "Calendar, Gmail, and Drive scopes approved",
      approved: true,
    },
    {
      key: "webhook_runbook_approved",
      label: "Gmail webhook and disable runbook reviewed",
      approved: true,
    },
    {
      key: "redaction_rules_approved",
      label: "Provider error redaction rules approved",
      approved: true,
    },
  ],
  approved_scopes: [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
  ],
  missing_config_names: [],
  missing_approval_keys: [],
  connection_counts: {
    calendar_connection_count: 1,
    gmail_connection_count: 1,
    drive_connection_count: 1,
    connected_calendar_account_count: 1,
    connected_gmail_account_count: 1,
    connected_drive_account_count: 1,
  },
  last_test_status: "passed",
  last_tested_at: "2026-06-09T00:00:00Z",
  last_error_redacted: null,
  readiness: "ready_for_user_connections",
};

export const googleWorkspaceReadinessTest = {
  provider: "google_workspace",
  status: "passed",
  checks: [
    {
      key: "GOOGLE_WORKSPACE_CLIENT_ID",
      label: "GOOGLE_WORKSPACE_CLIENT_ID",
      status: "passed",
      detail: null,
    },
  ],
  readiness: "ready_for_user_connections",
  tested_at: "2026-06-09T00:01:00Z",
};

export const providerCostProfiles = {
  cost_profiles: [
    {
      id: "cost-1",
      category: "case_refresh",
      provider: "case_tracking",
      currency: "INR",
      unit_amount_minor: 10,
      unit_amount_bps: null,
      unit_label: "refresh",
      effective_from: "2026-06-08T00:00:00Z",
      effective_until: null,
      status: "active",
      source: "provider invoice",
      tax_fee_notes: "GST and provider fees tracked separately.",
      cost_basis: "actual",
      confidence_level: "high",
      evidence_ref: "invoice-2026-06",
      founder_approval_status: "approved",
      approved_at: "2026-06-08T00:00:00Z",
      approved_by_platform_admin_id: "platform-1",
      notes: "Founder-reviewed refresh cost.",
      created_by_platform_admin_id: "platform-1",
      created_at: "2026-06-08T00:00:00Z",
      updated_at: "2026-06-08T00:00:00Z",
    },
  ],
};

export const marginSimulations = {
  simulations: [
    {
      id: "sim-1",
      scenario_name: "Founder smoke margin",
      currency: "INR",
      input: { revenue_minor: 1999900 },
      result: {
        revenue_minor: 1999900,
        total_variable_cost_minor: 250000,
        gross_profit_minor: 1749900,
        gross_margin_bps: 8750,
      },
      warnings: [],
      minimum_gross_margin_bps: 7000,
      uses_unapproved_estimated_costs: false,
      readiness_blocked: false,
      founder_approval_status: "approved",
      approved_at: "2026-06-08T00:00:00Z",
      approved_by_platform_admin_id: "platform-1",
      run_by_platform_admin_id: "platform-1",
      created_at: "2026-06-08T00:05:00Z",
    },
  ],
};

export const marginReadiness = {
  minimum_gross_margin_bps: 7000,
  blocked: true,
  required_scenarios: [
    {
      scenario_code: "solo_light_user",
      label: "Solo light user",
      latest_simulation_id: "sim-1",
      latest_gross_margin_bps: 8750,
      readiness_blocked: false,
      uses_unapproved_estimated_costs: false,
      missing: false,
    },
    {
      scenario_code: "abusive_usage_pattern",
      label: "Abusive usage pattern",
      latest_simulation_id: null,
      latest_gross_margin_bps: null,
      readiness_blocked: true,
      uses_unapproved_estimated_costs: true,
      missing: true,
    },
  ],
};

export const pineLabsUatReadiness = {
  run_id: "uat-run-1",
  run_status: "in_progress",
  provider_mode: "disabled",
  environment: "mock",
  complete: false,
  missing_required_scenarios: ["tampered_webhook"],
  production_activation_blocked: true,
  latest_decision: null,
  scenarios: [
    {
      scenario_code: "plan_payment_success",
      label: "Plan payment success",
      required: true,
      result_status: "pass",
      provider_order_id: "pl_order_1",
      webhook_id: "pl_evt_1",
      observed_at: "2026-06-08T00:10:00Z",
      operator_notes: "Recorded in mock harness.",
      attachment_refs: [],
    },
    {
      scenario_code: "tampered_webhook",
      label: "Tampered webhook",
      required: true,
      result_status: "pending",
      provider_order_id: null,
      webhook_id: null,
      observed_at: null,
      operator_notes: null,
      attachment_refs: [],
    },
  ],
};

export const billingSignoff = {
  signoff_id: "signoff-1",
  status: "in_progress",
  complete: false,
  missing_required_checks: ["tenant_no_leak_checks"],
  signed_off_at: null,
  notes: null,
  checks: [
    {
      check_code: "platform_admin",
      label: "/app/platform-admin",
      result_status: "pass",
      evidence_ref: "smoke-1",
      operator_notes: "Founder verified.",
      recorded_at: "2026-06-08T00:20:00Z",
    },
    {
      check_code: "tenant_no_leak_checks",
      label: "tenant no-leak checks",
      result_status: "pending",
      evidence_ref: null,
      operator_notes: null,
      recorded_at: null,
    },
  ],
};

export const passwordResetReadiness = {
  reset_link_domain: "app.caseops.ai",
  reset_path: "/account/reset-password",
  public_app_url: "https://app.caseops.ai",
  email_provider: "sendgrid",
  provider_configured: true,
  sender_email_configured: true,
  sender_name: "CaseOps",
  template_kind: "employee_password_reset_plain_text",
  subject_template: "Reset your {company_display_name} CaseOps password",
  token_ttl_minutes: 60,
  debug_tokens_allowed: false,
  non_prod_debug_tokens_only: true,
  secrets_exposed: false,
};

export const financeExceptions = {
  rows: [
    {
      id: "exception-1",
      exception_type: "amount_mismatch",
      severity: "high",
      status: "open",
      provider_order_id: "pl_order_2",
    },
  ],
};

export const platformSupportMatrix = {
  rows: [
    {
      id: "support-1",
      provider: "ecourtsindia",
      court: "Delhi High Court",
      bench_jurisdiction: "Delhi",
      lookup_method: "provider_api",
      refresh_cost_minor: 10,
      bulk_refresh_cost_minor: 5,
      currency: "INR",
      rate_limit: "60/min",
      freshness_sla: "Daily",
      legal_tos_status: "approved",
      failure_code_mapping: {},
      enabled: true,
      tenant_visible: true,
      status_notes: "Supported",
      evidence_ref: "court-matrix-2026-06",
      created_at: "2026-06-08T00:00:00Z",
      updated_at: "2026-06-08T00:00:00Z",
    },
  ],
};

export function mockBillingFetch(fetchMock: ReturnType<typeof vi.fn>) {
  fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/api/billing/plans")) return jsonResponse(planCatalog);
    if (url.includes("/api/billing/current")) return jsonResponse(currentBilling);
    if (url.includes("/api/billing/invoices") && url.includes("/download")) {
      return downloadResponse(
        url.includes("format=json") ? "caseops-invoice-inv-1.json" : "caseops-invoice-inv-1.pdf",
        url.includes("format=json") ? "{\"invoice_number\":\"SAAS-001\"}" : "%PDF-1.4",
      );
    }
    if (url.includes("/api/billing/invoices")) return jsonResponse(invoices);
    if (url.includes("/api/billing/credit-ledger/export")) {
      return downloadResponse("caseops-credit-ledger.csv");
    }
    if (url.includes("/api/billing/credit-ledger")) return jsonResponse(creditLedger);
    if (url.includes("/api/billing/reports/spend/export")) {
      return downloadResponse("caseops-spend-report.csv");
    }
    if (url.includes("/api/billing/reports/spend")) return jsonResponse(usageReport);
    if (url.includes("/api/billing/usage")) return jsonResponse(usageReport);
    if (url.includes("/api/billing/statement")) {
      return downloadResponse(
        url.includes("format=pdf") ? "caseops-billing-statement.pdf" : "caseops-billing-statement.csv",
      );
    }
    if (url.includes("/api/billing/payments/export")) {
      return downloadResponse("caseops-payments.csv");
    }
    if (url.includes("/api/billing/add-ons/checkout")) return jsonResponse(checkoutResponse);
    if (url.includes("/api/billing/add-ons")) {
      return jsonResponse({ version: planCatalog.version, plans: [], add_ons: planCatalog.add_ons });
    }
    if (url.includes("/api/billing/checkout") && init?.method === "POST") {
      return jsonResponse(checkoutResponse);
    }
    if (url.includes("/api/billing/enrollments/demo-request")) {
      return jsonResponse({ id: "demo-1", status: "new" });
    }
    if (url.includes("/api/platform-admin/overview")) return jsonResponse(platformOverview);
    if (url.includes("/api/platform-admin/enrollments")) return jsonResponse(enrollments);
    if (url.includes("/api/platform-admin/margin-alerts")) {
      return jsonResponse({ alerts: platformOverview.margin_alerts });
    }
    if (url.includes("/api/platform-admin/profit-report")) return jsonResponse(profitRows);
    if (url.includes("/api/platform-admin/companies/profitability")) {
      return jsonResponse(companyProfitability);
    }
    if (url.includes("/api/platform-admin/provider-events") && url.includes("/reprocess")) {
      return jsonResponse({ status: "queued_for_manual_reprocess" });
    }
    if (url.includes("/api/platform-admin/provider-events")) return jsonResponse(providerEvents);
    if (
      url.includes("/api/admin/google-workspace-configuration/test")
    ) {
      return jsonResponse(googleWorkspaceReadinessTest);
    }
    if (
      url.includes("/api/admin/google-workspace-configuration") &&
      init?.method === "PATCH"
    ) {
      return jsonResponse(googleWorkspaceConfiguration);
    }
    if (url.includes("/api/admin/google-workspace-configuration")) {
      return jsonResponse(googleWorkspaceConfiguration);
    }
    if (url.includes("/api/admin/integrations/health/check")) {
      return jsonResponse({
        checked_at: "2026-06-10T00:00:00Z",
        health: tenantIntegrationHealth.health,
      });
    }
    if (url.includes("/api/admin/integrations/health")) {
      return jsonResponse(tenantIntegrationHealth);
    }
    if (url.includes("/api/admin/integrations")) return jsonResponse(tenantIntegrations);
    if (url.includes("/api/drive/google/status")) return jsonResponse(googleDriveStatus);
    if (url.includes("/api/drive/google/files")) return jsonResponse(googleDriveFiles);
    if (url.includes("/api/drive/connections/")) {
      return jsonResponse({
        ...googleDriveStatus.connections[0],
        status: "revoked",
      });
    }
    if (url.includes("/api/drive/google/start")) {
      return jsonResponse({
        provider: "google_drive",
        provider_available: true,
        auth_url: null,
        unavailable_reason: null,
      });
    }
    if (url.includes("/api/platform-admin/integrations/health")) {
      return jsonResponse(platformIntegrationHealth);
    }
    if (url.includes("/api/platform-admin/integrations")) return jsonResponse(platformIntegrations);
    if (url.includes("/api/platform-admin/cost-profiles") && init?.method === "POST") {
      return jsonResponse({
        ...providerCostProfiles.cost_profiles[0],
        id: "cost-created",
      });
    }
    if (url.includes("/api/platform-admin/cost-profiles")) return jsonResponse(providerCostProfiles);
    if (url.includes("/api/platform-admin/margin-readiness")) {
      return jsonResponse(marginReadiness);
    }
    if (url.includes("/api/platform-admin/margin-simulations/run")) {
      return jsonResponse({
        ...marginSimulations.simulations[0],
        id: "sim-created",
      });
    }
    if (url.includes("/api/platform-admin/margin-simulations")) {
      return jsonResponse(marginSimulations);
    }
    if (url.includes("/api/platform-admin/pine-labs/uat-evidence")) {
      return jsonResponse({
        ...pineLabsUatReadiness,
        missing_required_scenarios: [],
        complete: true,
        production_activation_blocked: false,
      });
    }
    if (url.includes("/api/platform-admin/pine-labs/production-activation")) {
      return jsonResponse({ status: "recorded", production_activation_blocked: true });
    }
    if (url.includes("/api/platform-admin/pine-labs/uat-readiness")) {
      return jsonResponse(pineLabsUatReadiness);
    }
    if (url.includes("/api/platform-admin/billing-signoff/evidence")) {
      return jsonResponse({
        ...billingSignoff,
        missing_required_checks: [],
        complete: true,
      });
    }
    if (url.includes("/api/platform-admin/billing-signoff")) {
      return jsonResponse(billingSignoff);
    }
    if (url.includes("/api/platform-admin/password-reset-readiness")) {
      return jsonResponse(passwordResetReadiness);
    }
    if (url.includes("/api/platform-admin/finance/reconciliation-exceptions")) {
      return jsonResponse(financeExceptions);
    }
    if (url.includes("/api/platform-admin/case-tracking/support-matrix")) {
      return jsonResponse(platformSupportMatrix);
    }
    if (url.includes("/api/platform-admin/profit/export")) {
      return downloadResponse("caseops-platform-profit.csv");
    }
    if (url.includes("/api/platform-admin/revenue/export")) {
      return downloadResponse("caseops-platform-revenue.csv");
    }
    return jsonResponse({});
  });
}
