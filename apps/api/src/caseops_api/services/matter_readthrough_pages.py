"""Typed seven-layout packed reader; current source policy/DTO decode stay outside.

A candidate barrier selects at most2 physical25-slot pages before expansion.
Point reads take1 page and still require the exact requested identity/key.
Every canonical where-predicate is rebound to its same decoded source column;
there is no clean-serving hydration of a hidden original source relation.
"""

from sqlalchemy import (
    BigInteger,
    Integer,
    cast,
    column,
    exists,
    func,
    select,
    true,
    tuple_,
    union_all,
    values,
)
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import CTE

from caseops_api.db.matter_readthrough_page_models import (
    MatterDecisionReadPage,
    MatterHearingPackReadPage,
    MatterOptionReadPage,
    MatterPackItemReadPage,
    MatterReadthroughDirty,
    MatterRecommendationReadPage,
)
from caseops_api.db.matter_readthrough_page_schema_v1 import FIELDS

CAPACITY = 25
MODELS = {
    "recommendations": MatterRecommendationReadPage,
    "recommendation_options": MatterOptionReadPage,
    "recommendation_decisions": MatterDecisionReadPage,
    "hearing_packs": MatterHearingPackReadPage,
    "hearing_pack_items": MatterPackItemReadPage,
}


def _dirty(company_id, matter_id):
    table = MatterReadthroughDirty.__table__
    return exists(
        select(table.c.transaction_id).where(
            table.c.transaction_id == func.txid_current_if_assigned(),
            table.c.company_id == company_id,
            table.c.matter_id == matter_id,
        )
    )


def _edge(page, layout):
    if layout == "id":
        return page.c.last_id
    key = page.c.last_rank if layout == "rank" else page.c.last_stamp
    return tuple_(key, page.c.last_id)


def _ordering(page, layout, ascending):
    keys = (
        [page.c.last_id]
        if layout == "id"
        else [
            page.c.last_rank if layout == "rank" else page.c.last_stamp,
            page.c.last_id,
        ]
    )
    return [key.asc() if ascending else key.desc() for key in keys]


def _decoded(entry, model, layout):
    fields = {}
    for name, cap in FIELDS[(model.__tablename__, layout)].items():
        fields[name] = (
            entry[name].as_string()
            if cap is not None
            else cast(entry[name].as_string(), model.__table__.c[name].type)
        )
        if cap is not None:
            fields[name + "_source_bytes"] = cast(
                entry[name + "_source_bytes"].as_string(), BigInteger
            )
    return fields


def _contains_target(expression, model):
    table = model.__table__
    return any(getattr(node, "table", None) is table for node in visitors.iterate(expression))


def _adapt(expression, model, fields):
    table = model.__table__

    def target_column(node):
        return getattr(node, "table", None) is table and getattr(node, "key", None) in fields

    if not any(target_column(node) for node in visitors.iterate(expression)):
        return expression

    def replace(node):
        if target_column(node):
            return fields[node.key]
        if isinstance(node, CTE) and not any(
            target_column(child) for child in visitors.iterate(node.element)
        ):
            # Parent/ACL leaf definitions have no column being rebound here.
            # Retain their exact statement-local identity: cloning them into
            # both committed/own-write branches can create unrelated CTEs with
            # one anonymous name on the engine compilation path.
            return node
        return None

    return visitors.replacement_traverse(expression, {}, replace)


def _packed(
    statement,
    model,
    *,
    company_id,
    matter_id,
    layout,
    parent_id,
    key,
    ascending,
    bound,
    after=None,
    identity=None,
    anchor_key=None,
    guard=None,
):
    if (model.__tablename__, layout) not in FIELDS or model.__tablename__ not in MODELS:
        raise ValueError("Unsupported retained read layout.")
    page = MODELS[model.__tablename__].__table__
    parent_key = "" if parent_id is None else parent_id
    independent = [
        criterion
        for criterion in statement._where_criteria
        if not _contains_target(criterion, model)
    ]
    dependent = [
        criterion for criterion in statement._where_criteria if _contains_target(criterion, model)
    ]
    candidate = select(page).where(
        page.c.company_id == company_id,
        page.c.matter_id == matter_id,
        page.c.layout == layout,
        page.c.parent_key == parent_key,
        *independent,
    )
    if guard is not None:
        candidate = candidate.where(guard)
    edge = _edge(page, layout)
    if identity is not None:
        needle = identity if layout == "id" else tuple_(anchor_key, identity)
        candidate = candidate.where(edge >= needle if ascending else edge <= needle)
    elif after is not None:
        # Strict boundary: an anchor at a physical leaf's last slot must not
        # consume either of the2 next candidate pages.
        needle = after[1] if layout == "id" else tuple_(after[0], after[1])
        candidate = candidate.where(edge > needle if ascending else edge < needle)
    candidate = (
        candidate.order_by(*_ordering(page, layout, ascending))
        .limit(1 if identity is not None else 2)
        .cte()
    )
    # The generative prefix preserves the anonymous name but does not retain
    # the object whose numeric identity created it. A real ClauseElement clone
    # anchors that origin for the returned tree's lifetime, so another CTE
    # cannot reuse its identity while this statement still owns the name.
    candidate = candidate._clone().prefix_with("MATERIALIZED", dialect="postgresql")
    slots = values(column("slot", Integer)).data([(n,) for n in range(CAPACITY)]).alias()
    entry = candidate.c.payload[slots.c.slot]
    fields = _decoded(entry, model, layout)
    columns = [fields[value.key].label(value.key) for value in statement.selected_columns]
    predicates = [
        candidate.c.company_id == company_id,
        candidate.c.matter_id == matter_id,
        candidate.c.layout == layout,
        candidate.c.parent_key == parent_key,
        slots.c.slot < candidate.c.record_count,
        entry.is_not(None),
        entry["__company_id"].as_string() == company_id,
        entry["__matter_id"].as_string() == matter_id,
        fields["id"].is_not(None),
        *(_adapt(criterion, model, fields) for criterion in dependent),
    ]
    if identity is not None:
        predicates.append(fields["id"] == identity)
        if layout != "id":
            predicates.append(fields[key.key] == anchor_key)
    order = [fields[key.key], fields["id"]] if key.key != "id" else [fields["id"]]
    return (
        select(*columns)
        .select_from(candidate.join(slots, true()))
        .where(*predicates)
        .order_by(*(value.asc() if ascending else value.desc() for value in order))
        .limit(bound)
    )


def _current(
    session,
    statement,
    model,
    *,
    company_id,
    matter_id,
    layout,
    parent_id,
    key,
    ascending,
    bound,
    after=None,
    identity=None,
    anchor_key=None,
):
    canonical = statement
    if identity is not None:
        canonical = canonical.where(model.id == identity)
        if layout != "id":
            canonical = canonical.where(key == anchor_key)
    ordering = [key, model.id] if key.key != "id" else [key]
    canonical = canonical.order_by(
        *(value.asc() if ascending else value.desc() for value in ordering)
    ).limit(bound)
    if session.get_bind().dialect.name != "postgresql":
        return canonical
    dirty = _dirty(company_id, matter_id)
    committed = _packed(
        statement,
        model,
        company_id=company_id,
        matter_id=matter_id,
        layout=layout,
        parent_id=parent_id,
        key=key,
        ascending=ascending,
        bound=bound,
        after=after,
        identity=identity,
        anchor_key=anchor_key,
        guard=~dirty,
    )
    # This predicate is evaluated by the same retained Select on everyexecute,
    # including new own source writes; it is never cached in Python.
    own = canonical.where(dirty)
    current = union_all(committed, own).subquery()
    ordering = [current.c[key.key], current.c.id] if key.key != "id" else [current.c.id]
    return (
        select(*current.c)
        .order_by(*(value.asc() if ascending else value.desc() for value in ordering))
        .limit(bound)
    )


def page_statement(
    session,
    statement,
    model,
    *,
    company_id,
    matter_id,
    layout,
    parent_id,
    key,
    ascending,
    limit,
    after=None,
    lookahead=True,
):
    if type(limit) is not int or not 1 <= limit <= CAPACITY or type(lookahead) is not bool:
        raise ValueError("Unsupported retained read limit.")
    return _current(
        session,
        statement,
        model,
        company_id=company_id,
        matter_id=matter_id,
        layout=layout,
        parent_id=parent_id,
        key=key,
        ascending=ascending,
        bound=limit + int(lookahead),
        after=after,
    )


def point_statement(
    session,
    statement,
    model,
    *,
    company_id,
    matter_id,
    identity,
    layout="id",
    parent_id=None,
    key=None,
    ascending=True,
    anchor_key=None,
):
    if key is None:
        key = model.id
    if layout != "id" and anchor_key is None:
        raise ValueError("An exact signed order key is required for this anchor.")
    return _current(
        session,
        statement,
        model,
        company_id=company_id,
        matter_id=matter_id,
        layout=layout,
        parent_id=parent_id,
        key=key,
        ascending=ascending,
        bound=1,
        identity=identity,
        anchor_key=anchor_key,
    )
