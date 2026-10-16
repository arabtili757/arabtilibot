"""Idempotent SQLite to MongoDB Atlas migration utility.

Preserves exact user relationships without data loss.
Creates a timestamped backup before migration.
Reports only aggregate counts, never individual user IDs or secrets.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pymongo
from pymongo import MongoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("migration")


class MigrationError(Exception):
    """Custom exception raised when migration verification fails."""

    pass


def create_sqlite_backup(source_path: Path, backup_dir: Path) -> Path:
    """Create a verified, timestamped backup of the SQLite database."""
    if not source_path.exists():
        raise FileNotFoundError(f"Source database file not found: {source_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"{source_path.stem}_backup_{timestamp}{source_path.suffix}"

    logger.info("Creating backup of SQLite database...")
    shutil.copy2(source_path, backup_file)

    # Verify backup integrity
    if not backup_file.exists() or backup_file.stat().st_size == 0:
        raise MigrationError(f"Backup file creation failed or is empty: {backup_file}")

    conn = sqlite3.connect(backup_file)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()
        if not result or result[0] != "ok":
            raise MigrationError(f"Backup database integrity check failed: {result}")
    finally:
        conn.close()

    logger.info(f"SQLite backup successfully created and verified: {backup_file.name}")
    return backup_file


def read_sqlite_users(source_path: Path) -> List[Dict[str, Any]]:
    """Read all user records from SQLite database."""
    conn = sqlite3.connect(source_path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT user_id, referrer_id, referrals_count FROM users")
        rows = cursor.fetchall()
        return [
            {
                "user_id": int(row["user_id"]),
                "referrer_id": int(row["referrer_id"]) if row["referrer_id"] is not None else None,
                "referrals_count": int(row["referrals_count"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def run_migration(
    source_path: Path,
    mongo_uri: str,
    db_name: str,
    backup_dir: Path = Path("backups"),
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute the idempotent SQLite to MongoDB migration.

    Returns summary dictionary with aggregate counts.
    """
    if not mongo_uri or not mongo_uri.strip():
        raise ValueError("MongoDB URI is empty. Cannot connect to MongoDB.")

    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source SQLite database not found: {source_path}")

    # 1. Create SQLite backup
    backup_path = create_sqlite_backup(source_path, backup_dir)

    # 2. Read source data
    users = read_sqlite_users(source_path)
    source_count = len(users)
    logger.info(f"Read {source_count} user record(s) from source SQLite database.")

    if dry_run:
        logger.info("Dry run requested. Skipping database writes.")
        return {
            "status": "dry_run",
            "source_records": source_count,
            "backup_file": str(backup_path),
            "verified_records": 0,
            "mismatches": 0,
        }

    # 3. Connect to MongoDB and set up indexes
    client: MongoClient = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    # Test connection
    client.admin.command("ping")
    db = client[db_name]
    collection = db["users"]

    # Ensure unique index on user_id
    collection.create_index([("user_id", pymongo.ASCENDING)], unique=True)
    collection.create_index([("referrer_id", pymongo.ASCENDING)])

    # 4. Safe, idempotent upsert
    now = datetime.now(timezone.utc)
    upserted_count = 0
    for u in users:
        collection.update_one(
            {"user_id": u["user_id"]},
            {
                "$setOnInsert": {
                    "user_id": u["user_id"],
                    "created_at": now,
                },
                "$set": {
                    "referrer_id": u["referrer_id"],
                    "referrals_count": u["referrals_count"],
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        upserted_count += 1

    logger.info(f"Upserted {upserted_count} record(s) into MongoDB.")

    # 5. Verification step: verify count and exact values
    dest_count = collection.count_documents({})
    verified_count = 0
    mismatch_count = 0

    for u in users:
        doc = collection.find_one({"user_id": u["user_id"]})
        if not doc:
            mismatch_count += 1
            continue

        if (
            doc.get("referrer_id") == u["referrer_id"]
            and doc.get("referrals_count") == u["referrals_count"]
        ):
            verified_count += 1
        else:
            mismatch_count += 1

    if mismatch_count > 0:
        client.close()
        raise MigrationError(
            f"Verification failed: {mismatch_count} record mismatch(es) detected. "
            f"Source SQLite database is intact. Backup is at: {backup_path}"
        )

    client.close()
    logger.info(
        f"Migration completed and verified successfully! "
        f"Source: {source_count}, Verified: {verified_count}, Mismatches: 0."
    )

    return {
        "status": "success",
        "source_records": source_count,
        "destination_total_records": dest_count,
        "verified_records": verified_count,
        "mismatches": 0,
        "backup_file": str(backup_path),
    }


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite users to MongoDB Atlas.")
    parser.add_argument(
        "--source",
        type=str,
        default=os.getenv("SQLITE_DB_PATH", "konkurs.db"),
        help="Path to source SQLite database (e.g. konkurs.db)",
    )
    parser.add_argument(
        "--mongo-uri",
        type=str,
        default=os.getenv("MONGODB_URI", ""),
        help="MongoDB connection URI",
    )
    parser.add_argument(
        "--db-name",
        type=str,
        default=os.getenv("MONGODB_DB_NAME", "arab_tili_marathon"),
        help="Target MongoDB database name",
    )
    parser.add_argument(
        "--backup-dir",
        type=str,
        default="backups",
        help="Directory to save timestamped SQLite backups",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate source data and create backup without writing to MongoDB",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Explicit confirmation flag to proceed with database writes",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        print("\n[MIGRATION SAFETY NOTICE]")
        print("Running migration writes to the database. To proceed, you must provide --confirm or use --dry-run.")
        print(f"Source DB: {args.source}")
        print(f"Target DB: {args.db_name}")
        sys.exit(1)

    try:
        result = run_migration(
            source_path=Path(args.source),
            mongo_uri=args.mongo_uri,
            db_name=args.db_name,
            backup_dir=Path(args.backup_dir),
            dry_run=args.dry_run,
        )
        print("\n=== MIGRATION SUMMARY ===")
        print(f"Status: {result['status'].upper()}")
        print(f"Source Records: {result['source_records']}")
        print(f"Verified Records: {result['verified_records']}")
        print(f"Mismatches: {result['mismatches']}")
        print(f"Backup Location: {result['backup_file']}")
        print("=========================\n")
    except Exception as e:
        logger.error(f"Migration error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
