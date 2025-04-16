#!/usr/bin/env python3
import os
import sqlite3

DB_NAME = "prompt_store.db"
TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    prompt_name TEXT PRIMARY KEY,
    content TEXT
);
"""

def create_database():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(TABLE_SCHEMA)
    conn.commit()
    conn.close()

def populate_prompts():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Iterate over .txt files in the current working directory.
    for filename in os.listdir('.'):
        if filename.endswith('.txt'):
            prompt_name = os.path.splitext(filename)[0]  # remove the extension
            try:
                with open(filename, 'r', encoding='utf-8') as file:
                    content = file.read()
                # Insert or replace the prompt in the table.
                c.execute(
                    "INSERT OR REPLACE INTO prompts (prompt_name, content) VALUES (?, ?)",
                    (prompt_name, content)
                )
                print(f"Inserted prompt '{prompt_name}' from '{filename}'.")
            except Exception as e:
                print(f"Failed to read {filename}: {e}")
    conn.commit()
    conn.close()

if __name__ == '__main__':
    create_database()
    populate_prompts()
    print("Database creation and population complete!")
