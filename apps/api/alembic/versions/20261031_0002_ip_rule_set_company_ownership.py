"""Give every IP rule set exactly one owning company (IPLF-027B A1 expand).

Revision ID: 20261031_0002
Revises: 20261031_0001
DATA-GOVERNANCE-MAP: updated
Map: docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml.
``ip_rule_sets.company_id`` is a tenant ownership identifier under the table's
existing tenant-restricted legal-content profile. No new retention, provider
transmission or disposition is authorized.

Rule-set keys were globally unique, so two tenants proposing the same key shared
one identity and its version numbering, and a scope mismatch told a tenant that
another tenant's rule existed. This revision adds nullable company ownership
(expand only), backfills it from the ownership evidence already recorded on
versions, company policies and legal deadlines, and replaces the global key
constraint with a per-company one. A rule set whose evidence names no company
or more than one company is reported and the migration fails: ownership is
never guessed. A company policy may then only reference a rule set owned by
the same company.

MIGRATION-LOCK-RISK: acknowledged. Both tables are governance tables quiesced by
the A0 fence (production holds one rule set and one policy); the backfill and
constraint builds are bounded by env.py's migration lock and statement budgets.
MIGRATION-ROLLBACK: restore-forward. Do not downgrade after ownership has been
backfilled or after any A1 writer ran; the A0 rollback image reads the same rows.
"""

from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa

from alembic import op

revision = "20261031_0002"
down_revision = "20261031_0001"
branch_labels = None
depends_on = None

_RULE_SETS = "ip_rule_sets"
_POLICIES = "company_ip_rule_policies"

# Every place the pre-A1 schema records which company a rule set's evidence
# belongs to. Versions carry their proposer, fixture reviewer and legal
# approver; policies and deadlines carry their company directly.
_OWNERSHIP_EVIDENCE = sa.text(
    """
    SELECT v.rule_set_id AS rule_set_id, m.company_id AS company_id,
           'version_proposer' AS source
    FROM ip_rule_versions v
    JOIN company_memberships m ON m.id = v.proposed_by_membership_id
    UNION ALL
    SELECT v.rule_set_id, m.company_id, 'version_reviewer'
    FROM ip_rule_versions v
    JOIN company_memberships m ON m.id = v.reviewed_by_membership_id
    UNION ALL
    SELECT v.rule_set_id, m.company_id, 'version_legal_approver'
    FROM ip_rule_versions v
    JOIN company_memberships m ON m.id = v.legal_approved_by_membership_id
    UNION ALL
    SELECT p.rule_set_id, p.company_id, 'company_policy'
    FROM company_ip_rule_policies p
    UNION ALL
    SELECT v.rule_set_id, d.company_id, 'legal_deadline'
    FROM ip_deadlines d
    JOIN ip_rule_versions v ON v.id = d.rule_version_id
    """
)


def ownership_findings(bind) -> tuple[dict[str, str], list[str]]:
    """Return ``{rule_set_id: company_id}`` and every ambiguity, without writing.

    Shared by the upgrade and by the A1 reconciliation tests so the check that
    gates the migration is the one that is tested.
    """

    evidence: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in bind.execute(_OWNERSHIP_EVIDENCE).mappings():
        evidence[str(row["rule_set_id"])][str(row["company_id"])].add(str(row["source"]))
    resolved: dict[str, str] = {}
    findings: list[str] = []
    rule_sets = bind.execute(
        sa.text(f"SELECT id, company_id FROM {_RULE_SETS} ORDER BY id")
    ).mappings()
    for row in rule_sets:
        rule_set_id = str(row["id"])
        companies = dict(evidence.get(rule_set_id, {}))
        if row["company_id"] is not None:
            companies.setdefault(str(row["company_id"]), set()).add("rule_set_owner")
        if len(companies) == 1:
            resolved[rule_set_id] = next(iter(companies))
            continue
        if not companies:
            findings.append(f"{rule_set_id}: no ownership evidence")
            continue
        detail = "; ".join(
            f"{company_id} via {','.join(sorted(sources))}"
            for company_id, sources in sorted(companies.items())
        )
        findings.append(f"{rule_set_id}: {len(companies)} companies ({detail})")
    return resolved, findings


def _assert_unambiguous(bind) -> dict[str, str]:
    resolved, findings = ownership_findings(bind)
    if findings:
        raise RuntimeError(
            "IP rule-set ownership is ambiguous; refusing to guess. Reconcile each "
            "listed rule set to one company before rerunning this migration: "
            + " | ".join(findings)
        )
    return resolved


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(_RULE_SETS)}
    if "company_id" not in columns:
        with op.batch_alter_table(_RULE_SETS) as batch:
            batch.add_column(sa.Column("company_id", sa.String(36), nullable=True))
            batch.create_foreign_key(
                "fk_ip_rule_sets_company_id_companies",
                "companies",
                ["company_id"],
                ["id"],
                ondelete="CASCADE",
            )

    resolved = _assert_unambiguous(bind)
    for rule_set_id, company_id in sorted(resolved.items()):
        bind.execute(
            sa.text(
                f"UPDATE {_RULE_SETS} SET company_id = :company_id "
                "WHERE id = :rule_set_id AND company_id IS NULL"
            ),
            {"company_id": company_id, "rule_set_id": rule_set_id},
        )

    # Reconciliation: re-derive after the write. Every row is owned, and every
    # piece of recorded evidence agrees with that owner.
    _assert_unambiguous(bind)
    unowned = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {_RULE_SETS} WHERE company_id IS NULL")
    ).scalar_one()
    if unowned:
        raise RuntimeError(f"{unowned} IP rule set(s) remain without an owning company.")

    with op.batch_alter_table(_RULE_SETS) as batch:
        batch.drop_constraint("uq_ip_rule_set_key", type_="unique")
        batch.create_unique_constraint("uq_ip_rule_set_company_key", ["company_id", "key"])
        batch.create_unique_constraint("uq_ip_rule_set_id_company", ["id", "company_id"])

    with op.batch_alter_table(_POLICIES) as batch:
        batch.create_foreign_key(
            "fk_company_ip_policy_rule_set_company",
            _RULE_SETS,
            ["rule_set_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    raise RuntimeError(
        "IP rule-set ownership is restore-forward only; the A0 image reads this schema."
    )
