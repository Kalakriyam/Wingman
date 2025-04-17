"""

This script creates prompt_store.db (if missing), guarantees the right table layout
and feeds the default and obsidian profiles from local .txt files.

Table: prompts(
        prompt_name     TEXT PRIMARY KEY,   -- profile id
        system_prompt   TEXT,
        dynamic_context TEXT,
        voice           TEXT
)

The script is fully extensible:
add more `"some_file.txt": ("profile_name", "column_name")` entries to FILE_PROFILE_MAPPING and it will auto load them.

"""

import sqlite3
from pathlib import Path

DATABASE_FILE = Path("prompt_store.db")

TABLE_DEFINITION_SQL = """
CREATE TABLE IF NOT EXISTS prompts (
    prompt_name     TEXT PRIMARY KEY,
    system_prompt   TEXT,
    dynamic_context TEXT,
    voice           TEXT
);
"""

# filename           -> (profile, column)
FILE_PROFILE_MAPPING = {
    "system_prompt.txt":         ("default",  "system_prompt"),
    "dynamic_context.txt":       ("default",  "dynamic_context"),
    "obsidian_agent_prompt.txt": ("obsidian", "system_prompt"),
}

def ensure_database_and_table() -> sqlite3.Connection:
    """Create DB and table if they do not yet exist, then return the connection."""
    connection = sqlite3.connect(DATABASE_FILE)
    connection.execute(TABLE_DEFINITION_SQL)
    connection.commit()
    return connection

def upsert_column(connection: sqlite3.Connection,
                  profile: str,
                  column: str,
                  content: str) -> None:
    """
    Insert or update one column for a profile in a single statement.
    Other columns in that row stay untouched.
    """
    connection.execute(
        f"""
        INSERT INTO prompts (prompt_name, {column})
        VALUES (?, ?)
        ON CONFLICT(prompt_name) DO UPDATE SET
            {column} = excluded.{column};
        """,
        (profile, content)
    )
    connection.commit()

def main() -> None:
    connection = ensure_database_and_table()

    for filename, (profile, column) in FILE_PROFILE_MAPPING.items():
        file_path = Path(filename)
        if not file_path.is_file():
            print(f"⚠️  '{filename}' not found – skipped.")
            continue

        file_content = file_path.read_text(encoding="utf-8").strip()
        upsert_column(connection, profile, column, file_content)
        print(f"✔ Stored {column} for profile '{profile}' from '{filename}'.")

    connection.close()
    print("Database creation and population complete!")

if __name__ == "__main__":
    main()
