#!/usr/bin/env python3
"""
copy_prompts_to_modes.py

Overwrites the `modes` table with the full contents of the `prompts` table
inside `modes_and_prompts.db`.

• If `modes` already exists it is dropped and rebuilt with the exact same
  schema as `prompts`, then repopulated.
• If `prompts` is missing, the script aborts with a clear message.
"""

from pathlib import Path
import sqlite3
import sys

DB_PATH = Path("modes_and_prompts.db")


def main() -> None:
    if not DB_PATH.exists():
        sys.exit(f"❌ Database {DB_PATH} not found")

    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()

        # ---- 1. check the source table exists ----
        cur.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='prompts';"
        )
        row = cur.fetchone()
        if row is None:
            sys.exit("❌ Table 'prompts' does not exist – nothing to copy")

        create_prompts_sql: str = row[0]

        # ---- 2. rebuild the 'modes' table with identical schema ----
        create_modes_sql: str = create_prompts_sql.replace(
            "CREATE TABLE prompts", "CREATE TABLE modes", 1
        )

        conn.executescript(
            "DROP TABLE IF EXISTS modes;"  # remove old table
            + create_modes_sql             # create new one
        )
        print("✔ Recreated table 'modes' with prompts schema")

        # ---- 3. copy rows ----
        conn.execute("INSERT INTO modes SELECT * FROM prompts;")
        conn.commit()

        # ---- 4. report ----
        count = cur.execute("SELECT COUNT(*) FROM modes;").fetchone()[0]
        print(f"✅ Copied {count} rows from 'prompts' into 'modes'")


if __name__ == "__main__":
    main()
