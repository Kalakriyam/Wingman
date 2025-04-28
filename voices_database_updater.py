#!/usr/bin/env python3
"""
initialize_voices_settings.py

Ensures a `settings` table exists in `modes_and_prompts.db`
and stores the `voices` JSON there (insert or replace).
"""

import json
import sqlite3
from pathlib import Path

# ---------- USER-EDITABLE SECTION ----------
DATABASE_FILENAME: str = "modes_and_prompts.db"

voices_dict: dict[str, str] = {
    "Martin_int": "a5n9pJUnAhX4fn7lx3uo",
    "Frank": "gFwlAMshRYWaSeoMt2md",
    "Robert": "BtWabtumIemAotTjP5sk",
    "George": "Yko7PKHZNXotIFUBG7I9",
    "Educational_Elias": "bYS7cEY0uRew5lIOkGCu",
    "Will": "bIHbv24MWmeRgasZH58o",
    "David_conversational": "EozfaQ3ZX0esAp1cW5nG",
    "Harrison": "fCxG8OHm4STbIsWe4aT9",
}
# ---------- END USER-EDITABLE SECTION ----------


def main() -> None:
    """Create table if needed and upsert the voices JSON."""
    database_path: Path = Path(__file__).with_name(DATABASE_FILENAME)

    with sqlite3.connect(database_path) as connection:
        cursor = connection.cursor()

        # 1. Make sure the table exists
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )

        # 2. Store / update the voices dict as JSON
        voices_json: str = json.dumps(voices_dict, ensure_ascii=False, indent=2)
        cursor.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE
                  SET value = excluded.value;
            """,
            ("voices", voices_json),
        )

        connection.commit()

    print(f"✅ Voices list stored in {database_path}")


if __name__ == "__main__":
    main()
