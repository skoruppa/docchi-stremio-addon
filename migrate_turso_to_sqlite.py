#!/usr/bin/env python3
"""Migrate all data from Turso to local SQLite.

Usage:
    .venv/bin/python migrate_turso_to_sqlite.py

This will:
1. Connect to Turso and download all meta_cache, videos_cache, season_episodes_cache
2. Write them to local SQLite at the configured DATABASE path
3. Print stats and verify counts match

After running, set TURSO_URL= and TURSO_TOKEN= empty in .env to switch to SQLite.
"""
import asyncio
import os
import sys
import sqlite3
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()


async def main():
    from config import Config

    if not Config.TURSO_URL or not Config.TURSO_TOKEN:
        print("ERROR: TURSO_URL and TURSO_TOKEN must be set in .env to migrate FROM Turso")
        sys.exit(1)

    import libsql_client
    turso_url = Config.TURSO_URL.replace('libsql://', 'https://')

    # Target SQLite
    db_path = os.environ.get('MIGRATE_DB_PATH', Config.DATABASE)
    print(f"Source: Turso ({turso_url})")
    print(f"Target: SQLite ({db_path})")
    print()

    # Connect to Turso
    async with libsql_client.create_client(url=turso_url, auth_token=Config.TURSO_TOKEN) as client:

        # --- Count source rows ---
        tables = ['meta_cache', 'videos_cache', 'season_episodes_cache']
        turso_counts = {}
        for table in tables:
            try:
                rs = await client.execute(f"SELECT COUNT(*) FROM {table}")
                turso_counts[table] = rs.rows[0][0] if rs.rows else 0
            except Exception as e:
                print(f"  WARNING: {table} not found in Turso ({e})")
                turso_counts[table] = 0

        print("Turso row counts:")
        for t, c in turso_counts.items():
            print(f"  {t}: {c}")
        print()

        total = sum(turso_counts.values())
        if total == 0:
            print("Nothing to migrate!")
            return

        # --- Open local SQLite ---
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta_cache (
                mal_id TEXT PRIMARY KEY,
                meta TEXT,
                timestamp INTEGER
            );
            CREATE TABLE IF NOT EXISTS videos_cache (
                mal_id TEXT PRIMARY KEY,
                videos TEXT,
                timestamp INTEGER
            );
            CREATE TABLE IF NOT EXISTS season_episodes_cache (
                cache_key TEXT PRIMARY KEY,
                episodes TEXT,
                timestamp INTEGER
            );
        """)
        conn.commit()

        # --- Migrate meta_cache ---
        if turso_counts['meta_cache'] > 0:
            print(f"Migrating meta_cache ({turso_counts['meta_cache']} rows)...")
            offset = 0
            batch_size = 200
            migrated = 0
            while offset < turso_counts['meta_cache']:
                rs = await client.execute(
                    f"SELECT mal_id, meta, timestamp FROM meta_cache LIMIT {batch_size} OFFSET {offset}"
                )
                if not rs.rows:
                    break
                rows = [(r[0], r[1], r[2]) for r in rs.rows]
                conn.executemany(
                    "INSERT OR REPLACE INTO meta_cache (mal_id, meta, timestamp) VALUES (?,?,?)",
                    rows
                )
                conn.commit()
                migrated += len(rows)
                offset += batch_size
                print(f"  {migrated}/{turso_counts['meta_cache']}")
            print(f"  Done: {migrated} rows")

        # --- Migrate videos_cache ---
        if turso_counts['videos_cache'] > 0:
            print(f"Migrating videos_cache ({turso_counts['videos_cache']} rows)...")
            offset = 0
            batch_size = 100  # videos can be large
            migrated = 0
            while offset < turso_counts['videos_cache']:
                rs = await client.execute(
                    f"SELECT mal_id, videos, timestamp FROM videos_cache LIMIT {batch_size} OFFSET {offset}"
                )
                if not rs.rows:
                    break
                rows = [(r[0], r[1], r[2]) for r in rs.rows]
                conn.executemany(
                    "INSERT OR REPLACE INTO videos_cache (mal_id, videos, timestamp) VALUES (?,?,?)",
                    rows
                )
                conn.commit()
                migrated += len(rows)
                offset += batch_size
                print(f"  {migrated}/{turso_counts['videos_cache']}")
            print(f"  Done: {migrated} rows")

        # --- Migrate season_episodes_cache ---
        if turso_counts['season_episodes_cache'] > 0:
            print(f"Migrating season_episodes_cache ({turso_counts['season_episodes_cache']} rows)...")
            offset = 0
            batch_size = 200
            migrated = 0
            while offset < turso_counts['season_episodes_cache']:
                rs = await client.execute(
                    f"SELECT cache_key, episodes, timestamp FROM season_episodes_cache LIMIT {batch_size} OFFSET {offset}"
                )
                if not rs.rows:
                    break
                rows = [(r[0], r[1], r[2]) for r in rs.rows]
                conn.executemany(
                    "INSERT OR REPLACE INTO season_episodes_cache (cache_key, episodes, timestamp) VALUES (?,?,?)",
                    rows
                )
                conn.commit()
                migrated += len(rows)
                offset += batch_size
                print(f"  {migrated}/{turso_counts['season_episodes_cache']}")
            print(f"  Done: {migrated} rows")

    # --- Verify ---
    print("\nVerifying local SQLite...")
    for table in tables:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        local_count = cur.fetchone()[0]
        match = "✓" if local_count >= turso_counts[table] else "✗ MISMATCH"
        print(f"  {table}: {local_count} (Turso: {turso_counts[table]}) {match}")

    conn.close()
    print(f"\nMigration complete! SQLite file: {db_path}")
    print(f"File size: {os.path.getsize(db_path) / 1024 / 1024:.1f} MB")
    print()
    print("Next steps:")
    print("  1. Set TURSO_URL= and TURSO_TOKEN= to empty in .env")
    print("  2. Mount the SQLite file as a Docker volume so it persists across restarts")
    print("     Example: docker run -v ./data/database.db:/tmp/database.db ...")
    print("  3. Restart the app")


if __name__ == "__main__":
    asyncio.run(main())
