from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every backend. SQLite drops tzinfo on the way back, which made
    API timestamps serialise without an offset and browsers read them as local time."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# BIGINT autoincrement that still works on SQLite (which only autoincrements INTEGER PRIMARY KEY)
BigID = BigInteger().with_variant(Integer, "sqlite")
JSONType = JSON().with_variant(JSON(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict: JSONType, list: JSONType}


class IdMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
