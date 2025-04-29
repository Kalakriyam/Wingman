#!/usr/bin/env python3
"""
migrate_settings.py
───────────────────
Creates a new `settings_manager.db` (if missing), migrates the voices list
out of `modes_and_prompts.db`, and deletes that old JSON entry.

• voices  → voices table (name, code)
• tts_models / general_settings tables are created empty (ready for use)
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict


OLD_DB = Path("modes_and_prompts.db")
NEW_DB = Path("settings_manager.db")


CREATE_TABLES_SQL: str = """
CREATE TABLE IF NOT EXISTS voices (
    name TEXT PRIMARY KEY,
    code TEXT
);
CREATE TABLE IF NOT EXISTS tts_models (
    name TEXT PRIMARY KEY,
    model_id TEXT
);
CREATE TABLE IF NOT EXISTS general_settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def load_voices_from_old_db(conn: sqlite3.Connection) -> Dict[str, str]:
    """Return the voices dict found in the old DB, else empty dict."""
    cur = conn.execute(
        "SELECT value FROM settings WHERE key = 'voices'"
    )
    row = cur.fetchone()
    return json.loads(row[0]) if row else {}


def delete_old_voices_row(conn: sqlite3.Connection) -> None:
    """Remove the voices JSON row from settings table (if present)."""
    conn.execute("DELETE FROM settings WHERE key = 'voices'")


def upsert_voices_in_new_db(conn: sqlite3.Connection, voices: Dict[str, str]) -> None:
    """Insert or replace every voice row in the new voices table."""
    conn.executemany(
        "INSERT OR REPLACE INTO voices (name, code) VALUES (?, ?)",
        list(voices.items()),
    )


def main() -> None:
    # ---------- 1. Read voices JSON from old DB (if the file exists) ----------
    voices: Dict[str, str] = {}
    if OLD_DB.exists():
        with sqlite3.connect(OLD_DB) as old_conn:
            voices = load_voices_from_old_db(old_conn)
            delete_old_voices_row(old_conn)
            old_conn.commit()
        print(f"✔ Removed voices JSON from {OLD_DB}")
    else:
        print(f"⚠ {OLD_DB} not found – skipping deletion step")

    if not voices:
        print("⚠ No voices found to migrate – nothing to copy")
        return

    # ---------- 2. Create new DB / tables and insert voices ----------
    with sqlite3.connect(NEW_DB) as new_conn:
        # create tables if they don't exist
        new_conn.executescript(CREATE_TABLES_SQL)
        upsert_voices_in_new_db(new_conn, voices)
        new_conn.commit()

    print(f"✅ Migrated {len(voices)} voices into {NEW_DB}")
    print("Done.")


if __name__ == "__main__":
    main()
