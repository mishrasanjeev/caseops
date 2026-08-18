"""DATA-GOV-08: a purge carries a dependency plan derived from the real schema.

A purge removes rows, so order matters: a child must go before the parent it
references. The order here is DERIVED from the live foreign-key graph rather
than maintained by hand, because a hand-written order stays correct exactly
until someone adds a relationship and does not remember the list.

Two properties are load-bearing and are tested as such.

`unsatisfied_dependencies` names tables that reference the scope without being
in it. Purging `legal_holds` without `legal_hold_items` either fails on the
constraint or - against a database configured to cascade - silently removes
preservation evidence the request never named.

`order_is_complete` exists because SQLAlchemy's `sorted_tables` warns about
unresolvable foreign-key cycles and then drops those edges: "Foreign key
constraints involving these tables will not be considered". An order that
quietly ignores some foreign keys is the exact failure a dependency plan is
supposed to prevent, so the cycle is reported instead of swallowed.
"""

from __future__ import annotations

from caseops_api.services.data_governance import purge_dependency_plan

_FOUNDATION_SCOPE = [
    "legal_holds",
    "legal_hold_items",
    "tenant_data_operations",
    "tenant_data_operation_items",
    "data_retention_policies",
    "data_retention_versions",
]


class TestDeletionOrder:
    def test_children_are_deleted_before_their_parents(self) -> None:
        plan = purge_dependency_plan(["legal_holds", "legal_hold_items"])
        order = plan["deletion_order"]

        assert order.index("legal_hold_items") < order.index("legal_holds")

    def test_every_foundation_pair_is_ordered_child_first(self) -> None:
        plan = purge_dependency_plan(_FOUNDATION_SCOPE)
        order = plan["deletion_order"]

        for child, parent in (
            ("legal_hold_items", "legal_holds"),
            ("tenant_data_operation_items", "tenant_data_operations"),
            ("data_retention_versions", "data_retention_policies"),
        ):
            assert order.index(child) < order.index(parent), (
                f"{child} must be removed before {parent}"
            )

    def test_only_requested_tables_appear(self) -> None:
        # The plan describes the requested purge, not the whole schema.
        plan = purge_dependency_plan(["legal_holds", "legal_hold_items"])

        assert set(plan["deletion_order"]) == {"legal_holds", "legal_hold_items"}

    def test_an_unknown_data_class_is_ignored_rather_than_invented(self) -> None:
        plan = purge_dependency_plan(["legal_holds", "not_a_real_table"])

        assert plan["deletion_order"] == ["legal_holds"]


class TestUnsatisfiedDependencies:
    def test_purging_a_parent_without_its_child_is_reported(self) -> None:
        plan = purge_dependency_plan(["legal_holds"])

        referencing = {entry["table"] for entry in plan["unsatisfied_dependencies"]}
        assert "legal_hold_items" in referencing, (
            "purging holds without their items would orphan or block preservation "
            "evidence the request never named"
        )

    def test_each_report_names_what_it_references_and_why(self) -> None:
        plan = purge_dependency_plan(["legal_holds"])

        for entry in plan["unsatisfied_dependencies"]:
            assert entry["references"] == "legal_holds"
            assert entry["detail"].strip()

    def test_including_the_child_clears_that_dependency(self) -> None:
        plan = purge_dependency_plan(["legal_holds", "legal_hold_items"])

        referencing = {entry["table"] for entry in plan["unsatisfied_dependencies"]}
        assert "legal_hold_items" not in referencing


class TestOrderCompleteness:
    def test_the_foundation_scope_yields_a_complete_order(self) -> None:
        plan = purge_dependency_plan(_FOUNDATION_SCOPE)

        assert plan["order_is_complete"] is True
        assert plan["unresolved_cycles"] == []

    def test_a_scope_inside_a_foreign_key_cycle_is_declared_incomplete(self) -> None:
        # `matters` and `company_memberships` sit in a mutually dependent group.
        # sorted_tables would return a confident order having silently discarded
        # the edges it could not satisfy.
        plan = purge_dependency_plan(["matters", "company_memberships"])

        assert plan["order_is_complete"] is False
        assert set(plan["unresolved_cycles"]) == {"matters", "company_memberships"}

    def test_cycles_outside_the_requested_scope_do_not_flag_it(self) -> None:
        # The schema contains a cycle, but it does not touch this request, so
        # the plan is still complete. Otherwise every purge would read as unsafe
        # and the signal would be worthless.
        plan = purge_dependency_plan(["legal_holds", "legal_hold_items"])

        assert plan["order_is_complete"] is True
