"""
Test fixtures.

We verify the schema against SQLite in-memory rather than a live Postgres
instance, purely for speed/portability in this environment. This exercises
every FK, UNIQUE, CHECK, and partial-unique-index constraint identically
to Postgres (see base.pg_enum and attempt.py's use of native_enum=False /
sqlite_where alongside postgresql_where specifically so the same
constraints apply on both backends). It does NOT verify Postgres-only
behavior (numeric precision edge cases, concurrent transaction isolation
under real MVCC). Run the same test file against a real Postgres URL
before deploying — swap DATABASE_URL below — as a final check.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.factory import create_app
from app.models import db as _db


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture()
def app():
    app = create_app(database_url="sqlite:///:memory:")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        # rounds.winning_attempt_id <-> attempts.round_id is a genuine
        # circular FK (by design - see round.py). SQLite can't ALTER TABLE
        # to add/drop a constraint after the fact the way Postgres can, so
        # tearing down an in-memory SQLite DB with FK enforcement on trips
        # over the cycle. This has no bearing on the real Postgres schema
        # (where use_alter=True handles it via a deferred ALTER TABLE) —
        # it's purely a SQLite-test-cleanup wrinkle, so we relax the
        # pragma just for teardown.
        _db.session.execute(_db.text("PRAGMA foreign_keys=OFF"))
        _db.drop_all()


@pytest.fixture()
def db(app):
    return _db
