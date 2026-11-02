"""Private PostgreSQL physical leaves; never a source of record/ACL authority."""

from caseops_api.db.base import Base
from caseops_api.db.matter_readthrough_page_schema_v1 import define_tables

_tables = define_tables(Base.metadata)


class MatterRecommendationReadPage(Base):
    __table__ = _tables["matter_recommendation_read_pages"]


class MatterOptionReadPage(Base):
    __table__ = _tables["matter_option_read_pages"]


class MatterDecisionReadPage(Base):
    __table__ = _tables["matter_decision_read_pages"]


class MatterHearingPackReadPage(Base):
    __table__ = _tables["matter_hearing_pack_read_pages"]


class MatterPackItemReadPage(Base):
    __table__ = _tables["matter_pack_item_read_pages"]


class MatterReadthroughDirty(Base):
    __table__ = _tables["matter_readthrough_dirty"]
