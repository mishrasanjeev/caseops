import { z } from "zod";

const id = z.string().min(1).max(255);
export const consoleAdminSelf = z.object({
  id, email: z.string().email(), full_name: z.string().min(1).max(255), role: z.enum(["manager", "viewer"]),
}).strict();
export const consoleAuthState = z.object({
  state: z.enum(["mfa_enrollment_required", "mfa_challenge_required", "authenticated"]),
  admin: consoleAdminSelf.nullable(), expires_at: z.string().datetime({ offset: true }),
  recovery_codes: z.array(z.string().min(1).max(128)).max(32).nullable().optional(),
}).strict().refine((value) => value.state !== "authenticated" || value.admin !== null, "Authenticated platform identity is required.");
export const consoleAdminRecord = consoleAdminSelf.extend({
  status: z.enum(["pending", "active", "revoked"]), created_at: z.string().datetime({ offset: true }),
}).strict();
export const consoleAdminsResponse = z.object({
  items: z.array(consoleAdminRecord).max(100), next_cursor: z.string().max(8192).nullable(),
}).strict();
export const consoleInvitationResponse = z.object({
  admin: consoleAdminRecord, delivery_status: z.enum(["pending", "accepted", "failed", "outcome_unknown"]),
}).strict();
export const consoleEnrollmentResponse = z.object({
  secret: z.string().min(1).max(256), otpauth_url: z.string().max(4096).startsWith("otpauth://totp/"),
}).strict();
export const consoleAccepted = z.object({ status: z.literal("accepted") }).strict();
export const consoleComplete = z.object({ status: z.literal("complete") }).strict();
export const consoleSignedOut = z.object({ status: z.literal("signed_out") }).strict();

const money = z.number().int().safe();
export const consoleUsageRecord = z.object({
  company_id: id, feature_key: z.string().max(255), quantity: money, credits: money, estimated_internal_cost_minor: money,
}).strict();
export const consoleProfitRecord = z.object({
  company_id: id, company_name: z.string().nullable(), period_start: z.string().datetime({ offset: true }), period_end: z.string().datetime({ offset: true }),
  gross_revenue_minor: money, recognized_revenue_minor: money, tax_minor: money, tax_collected_minor: money,
  discounts_minor: money, discount_minor: money, payment_provider_cost_minor: money, payment_gateway_cost_minor: money,
  llm_cost_minor: money, embedding_cost_minor: money, case_refresh_cost_minor: money, document_processing_cost_minor: money,
  storage_cost_minor: money, manual_support_cost_minor: money, manual_research_cost_minor: money,
  total_variable_cost_minor: money, gross_profit_minor: money, gross_margin_bps: money.nullable(), status: z.string(),
}).strict();
export const consoleRevenueRecord = z.object({
  paid_at: z.string().datetime({ offset: true }).nullable(), company_id: id, merchant_reference: z.string(),
  amount_paid_minor: money, tax_amount_minor: money,
}).strict();
export const consoleCompanyProfitRecord = z.object({
  company_id: id, company_name: z.string(), rollup_count: money,
  gross_revenue_minor: money.nullable(), recognized_revenue_minor: money.nullable(), tax_minor: money.nullable(),
  discounts_minor: money.nullable(), payment_provider_cost_minor: money.nullable(), payment_gateway_cost_minor: money.nullable(),
  llm_cost_minor: money.nullable(), embedding_cost_minor: money.nullable(), case_refresh_cost_minor: money.nullable(),
  document_processing_cost_minor: money.nullable(), storage_cost_minor: money.nullable(), manual_support_cost_minor: money.nullable(),
  manual_research_cost_minor: money.nullable(), total_variable_cost_minor: money.nullable(), gross_profit_minor: money.nullable(),
  gross_margin_bps: money.nullable(), loss_risk: z.boolean().nullable(),
}).strict();
export const consoleReportPage = z.object({
  items: z.array(z.union([consoleUsageRecord, consoleProfitRecord, consoleRevenueRecord, consoleCompanyProfitRecord])).max(100),
  generated_at: z.string().datetime({ offset: true }), next_cursor: z.string().max(8192).nullable(),
  has_more: z.boolean(), coverage: z.enum(["recorded_usage", "recorded_rollups", "recorded_payments"]),
}).strict();
export const consoleMarginAlert = z.object({
  company_id: id, gross_margin_bps: money.nullable(), gross_profit_minor: money,
}).strict();
export const consoleCostGuardrailAlert = z.object({
  type: z.literal("case_refresh_cost_guardrail"), severity: z.literal("warning"), category: z.string(),
  provider: z.string(), unit_amount_minor: money, message: z.string(),
}).strict();
export const consoleOverview = z.object({
  generated_at: z.string().datetime({ offset: true }), coverage: z.literal("recorded_rollups"), rollup_count: money,
  mrr_minor: money, arr_minor: money, active_subscriptions: money, trial_count: money, failed_payments: money,
  gross_revenue_minor: money.nullable(), recognized_revenue_minor: money.nullable(), total_variable_cost_minor: money.nullable(),
  gross_profit_minor: money.nullable(), gross_margin_bps: money.nullable(),
  margin_alerts: z.array(z.union([consoleMarginAlert, consoleCostGuardrailAlert])).max(100),
  margin_alerts_has_more: z.boolean(),
}).strict();

export type ConsoleAuth = z.infer<typeof consoleAuthState>;
export type ConsoleAdmin = z.infer<typeof consoleAdminRecord>;
export type ConsoleReport = z.infer<typeof consoleReportPage>;
export type ConsoleOverview = z.infer<typeof consoleOverview>;
