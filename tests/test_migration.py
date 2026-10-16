"""Unit tests for SQLite to MongoDB migration utility and backup integrity."""

import sqlite3
import tempfile
from pathlib import Path
import pytest
from database.migration import (
    MigrationError,
    create_sqlite_backup,
    read_sqlite_users,
    run_migration,
)


def create_sample_sqlite_db(db_path: Path):
    """Helper to populate a sample SQLite database."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE users (
                user_id INTEGER PRIMARY KEY,
                referrer_id INTEGER,
                referrals_count INTEGER DEFAULT 0
            )
            """
        )
        conn.execute("INSERT INTO users VALUES (1001, NULL, 2)")
        conn.execute("INSERT INTO users VALUES (1002, 1001, 1)")
        conn.execute("INSERT INTO users VALUES (1003, 1001, 0)")
        conn.commit()
    finally:
        conn.close()


def test_sqlite_backup_and_read():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_konkurs.db"
        backup_dir = tmp_path / "backups"

        create_sample_sqlite_db(db_path)

        # Create backup
        backup_file = create_sqlite_backup(db_path, backup_dir)
        assert backup_file.exists()
        assert backup_file.stat().st_size > 0
        assert "test_konkurs_backup_" in backup_file.name

        # Read users
        users = read_sqlite_users(db_path)
        assert len(users) == 3
        u1 = [u for u in users if u["user_id"] == 1001][0]
        assert u1["referrer_id"] is None
        assert u1["referrals_count"] == 2


def test_migration_dry_run():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_konkurs.db"
        backup_dir = tmp_path / "backups"

        create_sample_sqlite_db(db_path)

        res = run_migration(
            source_path=db_path,
            mongo_uri="mongodb://localhost:27017",
            db_name="test_db",
            backup_dir=backup_dir,
            dry_run=True,
        )

        assert res["status"] == "dry_run"
        assert res["source_records"] == 3
        assert Path(res["backup_file"]).exists()


def test_migration_requires_mongo_uri():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test.db"
        create_sample_sqlite_db(db_path)

        with pytest.raises(ValueError, match="MongoDB URI is empty"):
            run_migration(source_path=db_path, mongo_uri="", db_name="test_db")


class MockMongoCollection:
    def __init__(self):
        self.docs = {}

    def create_index(self, *args, **kwargs):
        pass

    def update_one(self, filter_dict, update_dict, upsert=False):
        uid = filter_dict["user_id"]
        if uid not in self.docs and upsert:
            self.docs[uid] = dict(update_dict.get("$setOnInsert", {}))
        if uid in self.docs:
            for k, v in update_dict.get("$set", {}).items():
                self.docs[uid][k] = v

    def count_documents(self, filter_dict):
        return len(self.docs)

    def find_one(self, filter_dict):
        uid = filter_dict.get("user_id")
        return self.docs.get(uid)


class MockMongoClient:
    def __init__(self, *args, **kwargs):
        self.collection = MockMongoCollection()
        self.admin = type("Admin", (), {"command": lambda *a, **kw: {"ok": 1}})()

    def __getitem__(self, db_name):
        return {"users": self.collection}

    def close(self):
        pass


def test_migration_full_execution_and_idempotency(monkeypatch):
    mock_client = MockMongoClient()
    monkeypatch.setattr("database.migration.MongoClient", lambda *a, **kw: mock_client)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_konkurs.db"
        backup_dir = tmp_path / "backups"

        create_sample_sqlite_db(db_path)

        # First run
        res1 = run_migration(
            source_path=db_path,
            mongo_uri="mongodb://localhost:27017",
            db_name="test_db",
            backup_dir=backup_dir,
            dry_run=False,
        )
        assert res1["status"] == "success"
        assert res1["source_records"] == 3
        assert res1["verified_records"] == 3
        assert res1["mismatches"] == 0
        assert mock_client.collection.count_documents({}) == 3

        # Second run (Idempotency check: rerun must not duplicate or corrupt counts)
        res2 = run_migration(
            source_path=db_path,
            mongo_uri="mongodb://localhost:27017",
            db_name="test_db",
            backup_dir=backup_dir,
            dry_run=False,
        )
        assert res2["status"] == "success"
        assert res2["source_records"] == 3
        assert res2["verified_records"] == 3
        assert res2["mismatches"] == 0
        # Count must still be 3, not 6
        assert mock_client.collection.count_documents({}) == 3
        # Field values must be intact
        doc = mock_client.collection.find_one({"user_id": 1001})
        assert doc["referrals_count"] == 2


def test_migration_fails_on_data_mismatch(monkeypatch):
    mock_client = MockMongoClient()
    monkeypatch.setattr("database.migration.MongoClient", lambda *a, **kw: mock_client)

    # Tamper with update_one to simulate data corruption during upsert
    def corrupt_update(filter_dict, update_dict, upsert=False):
        uid = filter_dict["user_id"]
        mock_client.collection.docs[uid] = {
            "user_id": uid,
            "referrer_id": 999999,  # Corrupted!
            "referrals_count": -1,   # Corrupted!
        }

    mock_client.collection.update_one = corrupt_update

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_konkurs.db"
        backup_dir = tmp_path / "backups"

        create_sample_sqlite_db(db_path)

        with pytest.raises(MigrationError, match="Verification failed"):
            run_migration(
                source_path=db_path,
                mongo_uri="mongodb://localhost:27017",
                db_name="test_db",
                backup_dir=backup_dir,
                dry_run=False,
            )
