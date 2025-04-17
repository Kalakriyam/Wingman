import sqlite3

DB_NAME = "prompt_store.db"

NEW_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    prompt_name TEXT PRIMARY KEY,
    system_prompt TEXT,
    dynamic_context TEXT,
    voice TEXT
);
"""

def update_database():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Maak eerst een backup van de oude tabel
    c.execute("ALTER TABLE prompts RENAME TO prompts_backup;")

    # Maak de nieuwe tabel aan        
    c.execute(NEW_TABLE_SCHEMA)

    # Haal oude data op uit de backup-tabel
    c.execute("SELECT prompt_name, content FROM prompts_backup;")
    rows = c.fetchall()

    # Vul de nieuwe tabel met oude data (system_prompt gevuld, dynamic_context en voice leeg)
    for prompt_name, content in rows:
        c.execute("""
            INSERT INTO prompts (prompt_name, system_prompt, dynamic_context, voice)
            VALUES (?, ?, ?, ?)
        """, (prompt_name, content, "", None))

    conn.commit()
    conn.close()
    print("Database succesvol bijgewerkt naar nieuwe structuur!")

if __name__ == '__main__':
    update_database()