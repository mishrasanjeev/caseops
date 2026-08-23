# Repository Data-Governance Map

Generated from `DATA_GOVERNANCE_MAP.yaml`; do not edit this view directly.

## Status

- Status: `repository_inventory_snapshot_policy_unapproved`
- Policy approval: `pending_named_human_approval`
- Canonical map SHA-256: `f863b492b9745f9a72080772c2bb384d12c1d403a64c84881bd1fc92649709f0`
- SQL tables: `272`
- SQL columns: `4223`
- ORM indexes: `1213`
- Alembic/raw index declarations: `546`
- Non-SQL data classes: `11`

## Boundary

This inventory does not claim approved retention bounds, legal-hold activation, tenant export, purge, offboarding, provider deletion, backup recovery/restore, residency, or data-governance/recovery milestone completion. The only current disposition behavior is fail-closed Definition-of-Ready validation. This release's tenant-scoped company-user lookup, deadline-coverage guards, standalone-deadline offboarding serialization, and bounded Today IP coverage stream expose existing registered SQL classes only. The Today stream is a read projection over ip_deadline_coverages, ip_docket_records, and matter_deadlines that reuses the existing IP docket access predicate; the web endpoint and generated OpenAPI contract changes add no SQL or non-SQL data class, new storage, or disposition authority. EG-009 narrows what failure paths persist: audit-export, authority-ingestion, court-sync, document-job, document-processing, embedding and legal-update errors now store redacted text instead of raw exception strings. This removes infrastructure detail from already-registered columns; it adds no SQL or non-SQL data class, no new storage, and no disposition authority.

## SQL table inventory

| Table | Policy profile | Columns | Disposition handler |
| --- | --- | ---: | --- |
| `account_setup_tokens` | `security_identity_control` | 10 | `registry_fail_closed` |
| `affidavit_intelligence_runs` | `tenant_operational_record` | 15 | `registry_fail_closed` |
| `affidavit_questions` | `tenant_operational_record` | 19 | `registry_fail_closed` |
| `affidavit_statements` | `tenant_operational_record` | 16 | `registry_fail_closed` |
| `agent_executions` | `tenant_operational_record` | 10 | `registry_fail_closed` |
| `agent_grants` | `tenant_operational_record` | 15 | `registry_fail_closed` |
| `agent_tool_calls` | `platform_operational_reference` | 9 | `registry_fail_closed` |
| `ai_governance_approvals` | `tenant_operational_record` | 16 | `registry_fail_closed` |
| `api_idempotency_records` | `tenant_operational_record` | 20 | `registry_fail_closed` |
| `audit_events` | `tenant_operational_record` | 16 | `registry_fail_closed` |
| `audit_export_jobs` | `tenant_operational_record` | 16 | `registry_fail_closed` |
| `authority_annotations` | `tenant_operational_record` | 10 | `registry_fail_closed` |
| `authority_citations` | `public_or_licensed_legal_reference` | 10 | `registry_fail_closed` |
| `authority_document_chunks` | `public_or_licensed_legal_reference` | 15 | `registry_fail_closed` |
| `authority_documents` | `public_or_licensed_legal_reference` | 26 | `registry_fail_closed` |
| `authority_ingestion_runs` | `public_or_licensed_legal_reference` | 9 | `registry_fail_closed` |
| `authority_research_reports` | `tenant_operational_record` | 11 | `registry_fail_closed` |
| `authority_search_observations` | `tenant_operational_record` | 12 | `registry_fail_closed` |
| `authority_statute_references` | `public_or_licensed_legal_reference` | 7 | `registry_fail_closed` |
| `benches` | `platform_operational_reference` | 6 | `registry_fail_closed` |
| `billing_accounts` | `billing_provider_evidence` | 10 | `registry_fail_closed` |
| `billing_admin_notes` | `billing_provider_evidence` | 8 | `registry_fail_closed` |
| `billing_chargeback_disputes` | `billing_provider_evidence` | 17 | `registry_fail_closed` |
| `billing_checkout_sessions` | `billing_provider_evidence` | 23 | `registry_fail_closed` |
| `billing_coupon_redemptions` | `billing_provider_evidence` | 9 | `registry_fail_closed` |
| `billing_coupons` | `billing_provider_evidence` | 18 | `registry_fail_closed` |
| `billing_credit_ledger` | `billing_provider_evidence` | 14 | `registry_fail_closed` |
| `billing_credit_notes` | `billing_provider_evidence` | 18 | `registry_fail_closed` |
| `billing_enrollments` | `billing_provider_evidence` | 19 | `registry_fail_closed` |
| `billing_manual_invoices` | `billing_provider_evidence` | 20 | `registry_fail_closed` |
| `billing_margin_simulations` | `billing_provider_evidence` | 16 | `registry_fail_closed` |
| `billing_overage_policies` | `billing_provider_evidence` | 12 | `registry_fail_closed` |
| `billing_payment_orders` | `billing_provider_evidence` | 21 | `registry_fail_closed` |
| `billing_plan_entitlements` | `billing_provider_evidence` | 5 | `registry_fail_closed` |
| `billing_plan_prices` | `billing_provider_evidence` | 11 | `registry_fail_closed` |
| `billing_plan_versions` | `billing_provider_evidence` | 12 | `registry_fail_closed` |
| `billing_profit_rollups` | `billing_provider_evidence` | 23 | `registry_fail_closed` |
| `billing_provider_events` | `billing_provider_evidence` | 17 | `registry_fail_closed` |
| `billing_provider_fee_reconciliations` | `billing_provider_evidence` | 12 | `registry_fail_closed` |
| `billing_reconciliation_exceptions` | `billing_provider_evidence` | 12 | `registry_fail_closed` |
| `billing_refund_records` | `billing_provider_evidence` | 19 | `registry_fail_closed` |
| `billing_settlement_imports` | `billing_provider_evidence` | 14 | `registry_fail_closed` |
| `billing_settlement_rows` | `billing_provider_evidence` | 17 | `registry_fail_closed` |
| `billing_subscription_items` | `billing_provider_evidence` | 13 | `registry_fail_closed` |
| `billing_subscriptions` | `billing_provider_evidence` | 24 | `registry_fail_closed` |
| `billing_tds_reconciliation_rows` | `billing_provider_evidence` | 19 | `registry_fail_closed` |
| `billing_usage_attribution` | `billing_provider_evidence` | 15 | `registry_fail_closed` |
| `billing_usage_events` | `billing_provider_evidence` | 12 | `registry_fail_closed` |
| `billing_usage_rollups` | `billing_provider_evidence` | 11 | `registry_fail_closed` |
| `bulk_import_jobs` | `tenant_operational_record` | 20 | `registry_fail_closed` |
| `calendar_event_candidates` | `tenant_operational_record` | 25 | `registry_fail_closed` |
| `calendar_event_syncs` | `tenant_operational_record` | 26 | `registry_fail_closed` |
| `calendar_projection_reconciliation_candidates` | `tenant_operational_record` | 18 | `registry_fail_closed` |
| `case_tracking_support_matrix` | `platform_operational_reference` | 20 | `registry_fail_closed` |
| `cause_list_exports` | `tenant_operational_record` | 12 | `registry_fail_closed` |
| `clients` | `tenant_restricted_legal_content` | 26 | `registry_fail_closed` |
| `communications` | `tenant_restricted_legal_content` | 20 | `registry_fail_closed` |
| `companies` | `platform_operational_reference` | 16 | `registry_fail_closed` |
| `company_ip_rule_policies` | `tenant_restricted_legal_content` | 11 | `registry_fail_closed` |
| `company_memberships` | `tenant_operational_record` | 8 | `registry_fail_closed` |
| `company_notice_ip_links` | `tenant_restricted_legal_content` | 8 | `registry_fail_closed` |
| `company_notice_matter_links` | `tenant_restricted_legal_content` | 5 | `registry_fail_closed` |
| `company_notices` | `tenant_restricted_legal_content` | 35 | `registry_fail_closed` |
| `connector_health_records` | `tenant_operational_record` | 24 | `registry_fail_closed` |
| `connector_secret_rotation_evidence` | `security_identity_control` | 15 | `registry_fail_closed` |
| `contract_activity` | `tenant_restricted_legal_content` | 7 | `registry_fail_closed` |
| `contract_attachment_chunks` | `tenant_restricted_legal_content` | 6 | `registry_fail_closed` |
| `contract_attachments` | `tenant_restricted_legal_content` | 18 | `registry_fail_closed` |
| `contract_clauses` | `tenant_restricted_legal_content` | 9 | `registry_fail_closed` |
| `contract_legal_references` | `tenant_restricted_legal_content` | 18 | `registry_fail_closed` |
| `contract_obligations` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `contract_playbook_rules` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `contract_term_suggestions` | `tenant_restricted_legal_content` | 15 | `registry_fail_closed` |
| `contracts` | `tenant_restricted_legal_content` | 21 | `registry_fail_closed` |
| `courts` | `public_or_licensed_legal_reference` | 10 | `registry_fail_closed` |
| `custom_roles` | `tenant_operational_record` | 14 | `registry_fail_closed` |
| `data_retention_policies` | `tenant_operational_record` | 9 | `registry_fail_closed` |
| `data_retention_versions` | `tenant_operational_record` | 27 | `registry_fail_closed` |
| `document_processing_jobs` | `tenant_restricted_legal_content` | 14 | `registry_fail_closed` |
| `domain_consumer_effects` | `tenant_operational_record` | 21 | `registry_fail_closed` |
| `domain_outbox_events` | `tenant_operational_record` | 36 | `registry_fail_closed` |
| `draft_reviews` | `tenant_restricted_legal_content` | 7 | `registry_fail_closed` |
| `draft_versions` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `drafting_data_extraction_fields` | `tenant_restricted_legal_content` | 20 | `registry_fail_closed` |
| `drafts` | `tenant_restricted_legal_content` | 12 | `registry_fail_closed` |
| `drive_file_candidates` | `tenant_operational_record` | 22 | `registry_fail_closed` |
| `drive_sync_controls` | `tenant_operational_record` | 11 | `registry_fail_closed` |
| `email_calendar_candidates` | `tenant_operational_record` | 20 | `registry_fail_closed` |
| `email_suppressions` | `tenant_operational_record` | 14 | `registry_fail_closed` |
| `email_templates` | `tenant_operational_record` | 12 | `registry_fail_closed` |
| `employee_bulk_import_jobs` | `tenant_operational_record` | 18 | `registry_fail_closed` |
| `employee_bulk_import_rows` | `tenant_operational_record` | 11 | `registry_fail_closed` |
| `employee_profiles` | `tenant_operational_record` | 17 | `registry_fail_closed` |
| `ethical_walls` | `security_identity_control` | 14 | `registry_fail_closed` |
| `evaluation_cases` | `platform_operational_reference` | 11 | `registry_fail_closed` |
| `evaluation_runs` | `platform_operational_reference` | 12 | `registry_fail_closed` |
| `forum_catalog_entries` | `public_or_licensed_legal_reference` | 17 | `registry_fail_closed` |
| `hearing_pack_items` | `platform_operational_reference` | 8 | `registry_fail_closed` |
| `hearing_packs` | `platform_operational_reference` | 11 | `registry_fail_closed` |
| `hearing_reminder_delivery_intents` | `platform_operational_reference` | 5 | `registry_fail_closed` |
| `hearing_reminders` | `tenant_operational_record` | 23 | `registry_fail_closed` |
| `in_app_notifications` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `inbound_email_aliases` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `inbound_email_events` | `tenant_operational_record` | 21 | `registry_fail_closed` |
| `ip_assets` | `tenant_restricted_legal_content` | 9 | `registry_fail_closed` |
| `ip_client_instructions` | `tenant_restricted_legal_content` | 25 | `registry_fail_closed` |
| `ip_control_review_exception_decisions` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_control_review_sample_evidence` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_control_review_signatures` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_cost_items` | `tenant_restricted_legal_content` | 26 | `registry_fail_closed` |
| `ip_deadline_coverages` | `tenant_restricted_legal_content` | 18 | `registry_fail_closed` |
| `ip_deadline_incident_actions` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_deadline_incident_impacts` | `tenant_restricted_legal_content` | 11 | `registry_fail_closed` |
| `ip_deadline_incident_notification_decisions` | `tenant_restricted_legal_content` | 12 | `registry_fail_closed` |
| `ip_deadline_incidents` | `tenant_restricted_legal_content` | 28 | `registry_fail_closed` |
| `ip_deadlines` | `tenant_restricted_legal_content` | 39 | `registry_fail_closed` |
| `ip_docket_control_reviews` | `tenant_restricted_legal_content` | 26 | `registry_fail_closed` |
| `ip_docket_events` | `tenant_restricted_legal_content` | 28 | `registry_fail_closed` |
| `ip_docket_queues` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_docket_records` | `tenant_restricted_legal_content` | 25 | `registry_fail_closed` |
| `ip_document_links` | `tenant_restricted_legal_content` | 13 | `registry_fail_closed` |
| `ip_document_taxonomy_aliases` | `tenant_restricted_legal_content` | 8 | `registry_fail_closed` |
| `ip_document_taxonomy_entries` | `tenant_restricted_legal_content` | 12 | `registry_fail_closed` |
| `ip_document_versions` | `tenant_restricted_legal_content` | 21 | `registry_fail_closed` |
| `ip_documents` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_evidence_candidates` | `tenant_restricted_legal_content` | 15 | `registry_fail_closed` |
| `ip_identifiers` | `tenant_restricted_legal_content` | 19 | `registry_fail_closed` |
| `ip_import_rows` | `tenant_restricted_legal_content` | 16 | `registry_fail_closed` |
| `ip_incident_kill_switches` | `tenant_restricted_legal_content` | 14 | `registry_fail_closed` |
| `ip_parties_and_roles` | `tenant_restricted_legal_content` | 11 | `registry_fail_closed` |
| `ip_portfolio_export_jobs` | `tenant_restricted_legal_content` | 15 | `registry_fail_closed` |
| `ip_portfolio_saved_views` | `tenant_restricted_legal_content` | 12 | `registry_fail_closed` |
| `ip_proceedings` | `tenant_restricted_legal_content` | 15 | `registry_fail_closed` |
| `ip_related_right_obligations` | `tenant_restricted_legal_content` | 15 | `registry_fail_closed` |
| `ip_relationships` | `tenant_restricted_legal_content` | 9 | `registry_fail_closed` |
| `ip_renewal_terms` | `tenant_restricted_legal_content` | 20 | `registry_fail_closed` |
| `ip_responsibility_assignments` | `tenant_restricted_legal_content` | 17 | `registry_fail_closed` |
| `ip_rule_sets` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_rule_versions` | `tenant_restricted_legal_content` | 22 | `registry_fail_closed` |
| `ip_title_interests` | `tenant_restricted_legal_content` | 12 | `registry_fail_closed` |
| `ip_trademark_particular_versions` | `tenant_restricted_legal_content` | 18 | `registry_fail_closed` |
| `ip_workflow_definitions` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `ip_workflow_versions` | `tenant_restricted_legal_content` | 38 | `registry_fail_closed` |
| `ip_workspace_configurations` | `tenant_restricted_legal_content` | 24 | `registry_fail_closed` |
| `ip_workspace_test_results` | `tenant_restricted_legal_content` | 12 | `registry_fail_closed` |
| `judge_aliases` | `public_or_licensed_legal_reference` | 7 | `registry_fail_closed` |
| `judge_appointments` | `public_or_licensed_legal_reference` | 10 | `registry_fail_closed` |
| `judge_authority_affinity` | `public_or_licensed_legal_reference` | 7 | `registry_fail_closed` |
| `judge_decision_index` | `public_or_licensed_legal_reference` | 8 | `registry_fail_closed` |
| `judge_statute_focus` | `public_or_licensed_legal_reference` | 7 | `registry_fail_closed` |
| `judges` | `public_or_licensed_legal_reference` | 8 | `registry_fail_closed` |
| `judgment_alert_rules` | `tenant_operational_record` | 17 | `registry_fail_closed` |
| `judgment_alerts` | `tenant_operational_record` | 11 | `registry_fail_closed` |
| `legal_hold_items` | `tenant_operational_record` | 8 | `registry_fail_closed` |
| `legal_holds` | `tenant_operational_record` | 18 | `registry_fail_closed` |
| `legal_knowledge_graph_edges` | `tenant_operational_record` | 14 | `registry_fail_closed` |
| `legal_knowledge_graph_nodes` | `tenant_operational_record` | 15 | `registry_fail_closed` |
| `legal_knowledge_graph_runs` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `legal_update_alerts` | `tenant_operational_record` | 30 | `registry_fail_closed` |
| `legal_update_source_records` | `public_or_licensed_legal_reference` | 24 | `registry_fail_closed` |
| `legal_update_source_runs` | `public_or_licensed_legal_reference` | 10 | `registry_fail_closed` |
| `legal_update_watchlists` | `tenant_operational_record` | 19 | `registry_fail_closed` |
| `legal_working_calendar_versions` | `tenant_operational_record` | 20 | `registry_fail_closed` |
| `legal_working_calendars` | `tenant_operational_record` | 8 | `registry_fail_closed` |
| `litigation_intelligence_review_actions` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `mailbox_attachment_candidates` | `tenant_restricted_legal_content` | 14 | `registry_fail_closed` |
| `mailbox_message_imports` | `tenant_operational_record` | 23 | `registry_fail_closed` |
| `mailbox_webhook_events` | `tenant_operational_record` | 14 | `registry_fail_closed` |
| `matter_access_grants` | `security_identity_control` | 15 | `registry_fail_closed` |
| `matter_activity` | `tenant_restricted_legal_content` | 7 | `registry_fail_closed` |
| `matter_attachment_annotations` | `tenant_restricted_legal_content` | 14 | `registry_fail_closed` |
| `matter_attachment_chunks` | `tenant_restricted_legal_content` | 10 | `registry_fail_closed` |
| `matter_attachments` | `tenant_restricted_legal_content` | 50 | `registry_fail_closed` |
| `matter_billing_profiles` | `billing_provider_evidence` | 29 | `registry_fail_closed` |
| `matter_billing_rates` | `billing_provider_evidence` | 14 | `registry_fail_closed` |
| `matter_bulk_import_jobs` | `tenant_restricted_legal_content` | 22 | `registry_fail_closed` |
| `matter_bulk_import_rows` | `tenant_restricted_legal_content` | 11 | `registry_fail_closed` |
| `matter_cause_list_entries` | `tenant_restricted_legal_content` | 15 | `registry_fail_closed` |
| `matter_client_assignments` | `tenant_restricted_legal_content` | 6 | `registry_fail_closed` |
| `matter_compliance_extraction_runs` | `tenant_restricted_legal_content` | 19 | `registry_fail_closed` |
| `matter_compliance_items` | `tenant_restricted_legal_content` | 30 | `registry_fail_closed` |
| `matter_conflict_checks` | `tenant_restricted_legal_content` | 14 | `registry_fail_closed` |
| `matter_court_orders` | `public_or_licensed_legal_reference` | 18 | `registry_fail_closed` |
| `matter_court_sync_jobs` | `tenant_restricted_legal_content` | 16 | `registry_fail_closed` |
| `matter_court_sync_runs` | `public_or_licensed_legal_reference` | 10 | `registry_fail_closed` |
| `matter_deadlines` | `tenant_restricted_legal_content` | 21 | `registry_fail_closed` |
| `matter_file_qa_entries` | `tenant_restricted_legal_content` | 16 | `registry_fail_closed` |
| `matter_hearings` | `tenant_restricted_legal_content` | 28 | `registry_fail_closed` |
| `matter_intake_requests` | `tenant_restricted_legal_content` | 17 | `registry_fail_closed` |
| `matter_invoice_exports` | `billing_provider_evidence` | 10 | `registry_fail_closed` |
| `matter_invoice_line_items` | `billing_provider_evidence` | 10 | `registry_fail_closed` |
| `matter_invoice_payment_attempts` | `billing_provider_evidence` | 20 | `registry_fail_closed` |
| `matter_invoices` | `billing_provider_evidence` | 37 | `registry_fail_closed` |
| `matter_next_hearing_history` | `tenant_restricted_legal_content` | 13 | `registry_fail_closed` |
| `matter_next_hearing_suggestions` | `tenant_restricted_legal_content` | 18 | `registry_fail_closed` |
| `matter_notes` | `tenant_restricted_legal_content` | 5 | `registry_fail_closed` |
| `matter_outside_counsel_assignments` | `tenant_restricted_legal_content` | 12 | `registry_fail_closed` |
| `matter_portal_grants` | `tenant_restricted_legal_content` | 8 | `registry_fail_closed` |
| `matter_proceeding_signals` | `tenant_restricted_legal_content` | 22 | `registry_fail_closed` |
| `matter_statute_references` | `public_or_licensed_legal_reference` | 8 | `registry_fail_closed` |
| `matter_strategy_entries` | `tenant_restricted_legal_content` | 13 | `registry_fail_closed` |
| `matter_tag_assignments` | `tenant_restricted_legal_content` | 7 | `registry_fail_closed` |
| `matter_tags` | `tenant_restricted_legal_content` | 8 | `registry_fail_closed` |
| `matter_tasks` | `tenant_restricted_legal_content` | 18 | `registry_fail_closed` |
| `matter_time_entries` | `tenant_restricted_legal_content` | 14 | `registry_fail_closed` |
| `matters` | `tenant_restricted_legal_content` | 52 | `registry_fail_closed` |
| `mock_hearing_questions` | `tenant_operational_record` | 20 | `registry_fail_closed` |
| `mock_hearing_responses` | `tenant_operational_record` | 23 | `registry_fail_closed` |
| `mock_hearing_sessions` | `tenant_operational_record` | 21 | `registry_fail_closed` |
| `model_runs` | `tenant_operational_record` | 14 | `registry_fail_closed` |
| `notification_delivery_events` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `notification_delivery_intents` | `tenant_operational_record` | 46 | `registry_fail_closed` |
| `notification_rules` | `tenant_operational_record` | 11 | `registry_fail_closed` |
| `outside_counsel` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `outside_counsel_spend_records` | `billing_provider_evidence` | 19 | `registry_fail_closed` |
| `payment_webhook_events` | `billing_provider_evidence` | 13 | `registry_fail_closed` |
| `pine_labs_production_activation_decisions` | `billing_provider_evidence` | 10 | `registry_fail_closed` |
| `pine_labs_uat_runs` | `billing_provider_evidence` | 11 | `registry_fail_closed` |
| `pine_labs_uat_scenario_evidence` | `billing_provider_evidence` | 16 | `registry_fail_closed` |
| `platform_admin_audit_events` | `tenant_operational_record` | 12 | `registry_fail_closed` |
| `platform_admin_memberships` | `platform_operational_reference` | 10 | `registry_fail_closed` |
| `platform_operational_readiness_evidence` | `platform_operational_reference` | 14 | `registry_fail_closed` |
| `portal_magic_links` | `security_identity_control` | 8 | `registry_fail_closed` |
| `portal_users` | `tenant_operational_record` | 10 | `registry_fail_closed` |
| `predictive_outcome_aggregate_snapshots` | `tenant_operational_record` | 26 | `registry_fail_closed` |
| `predictive_outcome_classifications` | `tenant_operational_record` | 22 | `registry_fail_closed` |
| `predictive_signal_evidence` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `predictive_signal_items` | `tenant_operational_record` | 16 | `registry_fail_closed` |
| `predictive_signal_runs` | `tenant_operational_record` | 12 | `registry_fail_closed` |
| `production_billing_signoff_evidence` | `billing_provider_evidence` | 11 | `registry_fail_closed` |
| `production_billing_signoffs` | `billing_provider_evidence` | 7 | `registry_fail_closed` |
| `provider_cost_profiles` | `platform_operational_reference` | 22 | `registry_fail_closed` |
| `recommendation_decisions` | `tenant_restricted_legal_content` | 7 | `registry_fail_closed` |
| `recommendation_options` | `tenant_restricted_legal_content` | 8 | `registry_fail_closed` |
| `recommendations` | `tenant_restricted_legal_content` | 19 | `registry_fail_closed` |
| `source_link_reports` | `tenant_operational_record` | 14 | `registry_fail_closed` |
| `statute_change_events` | `public_or_licensed_legal_reference` | 12 | `registry_fail_closed` |
| `statute_sections` | `public_or_licensed_legal_reference` | 40 | `registry_fail_closed` |
| `statute_source_conflicts` | `public_or_licensed_legal_reference` | 13 | `registry_fail_closed` |
| `statute_source_versions` | `public_or_licensed_legal_reference` | 26 | `registry_fail_closed` |
| `statutes` | `public_or_licensed_legal_reference` | 22 | `registry_fail_closed` |
| `team_memberships` | `platform_operational_reference` | 5 | `registry_fail_closed` |
| `teams` | `tenant_operational_record` | 9 | `registry_fail_closed` |
| `tenant_ai_policies` | `tenant_operational_record` | 15 | `registry_fail_closed` |
| `tenant_contract_playbook_rules` | `tenant_restricted_legal_content` | 13 | `registry_fail_closed` |
| `tenant_contract_playbooks` | `tenant_restricted_legal_content` | 11 | `registry_fail_closed` |
| `tenant_data_operation_items` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `tenant_data_operations` | `tenant_operational_record` | 25 | `registry_fail_closed` |
| `tenant_enterprise_identity_configurations` | `security_identity_control` | 15 | `registry_fail_closed` |
| `tenant_google_workspace_configurations` | `tenant_operational_record` | 23 | `registry_fail_closed` |
| `tenant_microsoft365_configurations` | `tenant_operational_record` | 19 | `registry_fail_closed` |
| `tenant_notification_preferences` | `tenant_operational_record` | 10 | `registry_fail_closed` |
| `tenant_outlook_configurations` | `tenant_operational_record` | 21 | `registry_fail_closed` |
| `tenant_security_policies` | `security_identity_control` | 9 | `registry_fail_closed` |
| `tracked_case_bookmarks` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `tracked_case_poll_runs` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `tracked_case_provider_operations` | `tenant_operational_record` | 23 | `registry_fail_closed` |
| `tracked_case_provider_snapshots` | `tenant_restricted_legal_content` | 11 | `registry_fail_closed` |
| `tracked_case_updates` | `tenant_operational_record` | 16 | `registry_fail_closed` |
| `tracked_cases` | `tenant_operational_record` | 30 | `registry_fail_closed` |
| `trademark_application_scopes` | `tenant_operational_record` | 9 | `registry_fail_closed` |
| `trademark_applications` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `trademark_representations` | `tenant_operational_record` | 10 | `registry_fail_closed` |
| `user_calendar_connections` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `user_drive_connections` | `tenant_operational_record` | 13 | `registry_fail_closed` |
| `user_mailbox_connections` | `tenant_operational_record` | 16 | `registry_fail_closed` |
| `user_mfa_recovery_codes` | `security_identity_control` | 6 | `registry_fail_closed` |
| `user_mfa_settings` | `security_identity_control` | 12 | `registry_fail_closed` |
| `user_mfa_step_ups` | `security_identity_control` | 8 | `registry_fail_closed` |
| `user_notification_preferences` | `tenant_operational_record` | 11 | `registry_fail_closed` |
| `users` | `platform_operational_reference` | 6 | `registry_fail_closed` |
| `voyage_usage` | `billing_provider_evidence` | 13 | `registry_fail_closed` |

## Known non-SQL data classes

| ID | Kind | Disposition handler |
| --- | --- | --- |
| `document-object-prefix-and-version` | `object_prefix_version` | `registry_fail_closed` |
| `document-materialization-cache` | `cache` | `registry_fail_closed` |
| `sql-relational-index-projections` | `sql_index_projection` | `registry_fail_closed` |
| `authority-document-pgvector-index` | `search_vector_index` | `registry_fail_closed` |
| `matter-attachment-pgvector-index` | `search_vector_index` | `registry_fail_closed` |
| `database-queues-outbox-and-dead-letter` | `queue_outbox_dead_letter` | `registry_fail_closed` |
| `application-logs-traces-and-metrics` | `log_trace_metric` | `registry_fail_closed` |
| `audit-export-artifacts` | `export_artifact` | `registry_fail_closed` |
| `llm-and-embedding-provider-held-content` | `provider_held_object` | `registry_fail_closed` |
| `connector-and-payment-provider-held-records` | `provider_held_object` | `registry_fail_closed` |
| `database-and-object-backups` | `backup` | `registry_fail_closed` |

## Change control

Any changed Alembic migration or registered storage/provider/telemetry boundary must update the machine-readable map. New migrations also require the marker `DATA-GOVERNANCE-MAP: updated`. The current handler is intentionally fail-closed and performs no data operation.
