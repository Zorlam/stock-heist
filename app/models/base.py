"""
Shared SQLAlchemy setup.

Import `db` from here in your Flask app factory (db.init_app(app)) and in
every model module. Keeping a single shared `db` object is what lets
Flask-SQLAlchemy wire everything together correctly.
"""

import uuid

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, CHAR

db = SQLAlchemy()


class GUID(TypeDecorator):
    """Platform-independent UUID column.

    Uses Postgres' native UUID type when running on Postgres (the real
    target), and falls back to a CHAR(36) storing the hex string when
    running on SQLite (used only for fast local model tests — see
    tests/test_data_model.py). This lets the exact same model definitions
    be exercised in both environments without duplicating the schema.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            return str(uuid.UUID(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


def new_uuid():
    return uuid.uuid4()


def pg_enum(enum_cls, name):
    """Enum column stored as VARCHAR + CHECK constraint (native_enum=False)
    rather than a native Postgres ENUM type, so new values can be added
    later with a plain migration instead of `ALTER TYPE ... ADD VALUE`.
    """
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )
