"""master 스키마 ORM (지시서 §3.1). append-only 규약은 §4.4 참조."""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import DATERANGE, JSONB, UUID

from app.models.base import Base

try:  # pragma: no cover - 임베딩 컬럼(선택 의존성)
    from pgvector.sqlalchemy import Vector
except Exception:  # noqa: BLE001
    Vector = None

SCHEMA = "master"


# --- 참조 어휘 ---
class Country(Base):
    __tablename__ = "country"
    __table_args__ = {"schema": SCHEMA}
    code = Column(CHAR(2), primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CountryLabel(Base):
    __tablename__ = "country_label"
    __table_args__ = {"schema": SCHEMA}
    code = Column(CHAR(2), ForeignKey(f"{SCHEMA}.country.code"), primary_key=True)
    lang = Column(CHAR(2), primary_key=True)
    label = Column(Text, nullable=False)


class TerritoryGroup(Base):
    __tablename__ = "territory_group"
    __table_args__ = {"schema": SCHEMA}
    code = Column(Text, primary_key=True)


class TerritoryGroupLabel(Base):
    __tablename__ = "territory_group_label"
    __table_args__ = {"schema": SCHEMA}
    code = Column(Text, ForeignKey(f"{SCHEMA}.territory_group.code"), primary_key=True)
    lang = Column(CHAR(2), primary_key=True)
    label = Column(Text, nullable=False)


class TerritoryGroupCountry(Base):
    __tablename__ = "territory_group_country"
    __table_args__ = {"schema": SCHEMA}
    group_code = Column(Text, ForeignKey(f"{SCHEMA}.territory_group.code"), primary_key=True)
    country_code = Column(CHAR(2), ForeignKey(f"{SCHEMA}.country.code"), primary_key=True)


class RightsTypeRef(Base):
    __tablename__ = "rights_type_ref"
    __table_args__ = {"schema": SCHEMA}
    code = Column(Text, primary_key=True)


class RightsTypeLabel(Base):
    __tablename__ = "rights_type_label"
    __table_args__ = {"schema": SCHEMA}
    code = Column(Text, ForeignKey(f"{SCHEMA}.rights_type_ref.code"), primary_key=True)
    lang = Column(CHAR(2), primary_key=True)
    label = Column(Text, nullable=False)


class ConflictCode(Base):
    __tablename__ = "conflict_code"
    __table_args__ = {"schema": SCHEMA}
    code = Column(Text, primary_key=True)
    severity = Column(Text, nullable=False)


class ConflictCodeTemplate(Base):
    __tablename__ = "conflict_code_template"
    __table_args__ = {"schema": SCHEMA}
    code = Column(Text, ForeignKey(f"{SCHEMA}.conflict_code.code"), primary_key=True)
    lang = Column(CHAR(2), primary_key=True)
    template = Column(Text, nullable=False)


# --- 핵심 ---
class Team(Base):
    __tablename__ = "team"
    __table_args__ = {"schema": SCHEMA}
    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name = Column(Text, nullable=False)
    pin_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Ip(Base):
    __tablename__ = "ip"
    __table_args__ = {"schema": SCHEMA}
    id = Column(BigInteger, primary_key=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.team.id"), nullable=False)
    title = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    activity = Column(Text, nullable=False, server_default="active")  # ip_activity_kind: active/deactive
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IpAlias(Base):
    __tablename__ = "ip_alias"
    # ix_ip_alias_norm(lower(alias_text)) 는 마이그레이션에서 생성한다.
    __table_args__ = {"schema": SCHEMA}
    id = Column(BigInteger, primary_key=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.team.id"), nullable=False)
    ip_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.ip.id", ondelete="CASCADE"), nullable=False)
    alias_text = Column(Text, nullable=False)
    lang = Column(CHAR(2), nullable=False)
    alias_type = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ContentAsset(Base):
    __tablename__ = "content_asset"
    __table_args__ = {"schema": SCHEMA}
    id = Column(BigInteger, primary_key=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.team.id"), nullable=False)
    ip_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.ip.id"), nullable=False)
    parent_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.content_asset.id"))
    scope_type = Column(Text, nullable=False)
    season_no = Column(Integer)
    episode_no = Column(Integer)
    edition_code = Column(Text)
    title = Column(Text)


class IpRelation(Base):
    __tablename__ = "ip_relation"
    __table_args__ = {"schema": SCHEMA}
    source_ip_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.ip.id"), primary_key=True)
    derived_ip_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.ip.id"), primary_key=True)
    relation_type = Column(Text, primary_key=True)


class Contract(Base):
    __tablename__ = "contract"
    __table_args__ = {"schema": SCHEMA}
    id = Column(BigInteger, primary_key=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.team.id"), nullable=False)
    title = Column(Text, nullable=False)
    contract_type = Column(Text)
    counterparty = Column(Text, nullable=False)
    signed_date = Column(Date)
    lang = Column(CHAR(2))
    amount = Column(Numeric)
    currency = Column(CHAR(3))
    current_history_id = Column(BigInteger)
    source_tmpid = Column(UUID(as_uuid=True), unique=True)
    status = Column(Text, nullable=False, server_default="draft")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ContractHistory(Base):
    __tablename__ = "contract_history"
    __table_args__ = (
        UniqueConstraint("contract_id", "version"),
        {"schema": SCHEMA},
    )
    id = Column(BigInteger, primary_key=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.team.id"), nullable=False)
    contract_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    version = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    conflict_report = Column(JSONB)
    file_path = Column(Text)
    raw_text = Column(Text)
    title = Column(Text)
    counterparty = Column(Text)
    signed_date = Column(Date)
    lang = Column(CHAR(2))
    amount = Column(Numeric)
    currency = Column(CHAR(3))
    parsed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ContractChunk(Base):
    __tablename__ = "contract_chunk"
    __table_args__ = {"schema": SCHEMA}
    id = Column(BigInteger, primary_key=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.team.id"), nullable=False)
    contract_history_id = Column(
        BigInteger, ForeignKey(f"{SCHEMA}.contract_history.id", ondelete="CASCADE"), nullable=False
    )
    clause_no = Column(Text)
    chunk_text = Column(Text, nullable=False)
    lang = Column(CHAR(2))
    page = Column(Integer)
    embedding = Column(Vector(1024)) if Vector is not None else Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RightsGrant(Base):
    """INSERT 전용. UPDATE 는 status/terminated_* 갱신에만 허용(§4.4)."""

    __tablename__ = "rights_grant"
    __table_args__ = (
        Index("ix_rg_lineage", "lineage_id", "created_at"),
        Index("ix_rg_contract", "contract_id", "status"),
        {"schema": SCHEMA},
    )
    id = Column(BigInteger, primary_key=True)
    team_id = Column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.team.id"), nullable=False)
    contract_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.contract.id"), nullable=False)
    contract_history_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.contract_history.id"), nullable=False)
    content_asset_id = Column(BigInteger, ForeignKey(f"{SCHEMA}.content_asset.id"), nullable=False)
    territory = Column(CHAR(2), ForeignKey(f"{SCHEMA}.country.code"), nullable=False)
    rights_type = Column(Text, ForeignKey(f"{SCHEMA}.rights_type_ref.code"), nullable=False)
    period = Column(DATERANGE, nullable=False)
    exclusivity = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    lineage_id = Column(BigInteger)
    conditions_raw = Column(JSONB)
    confidence = Column(Numeric(3, 2))
    evidence = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    terminated_at = Column(DateTime(timezone=True))
    terminated_reason = Column(Text)
