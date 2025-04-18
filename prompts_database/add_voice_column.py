import sqlite3

def add_voice_column_and_fill(db_path="prompt_store.db"):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Voeg kolom toe als die nog niet bestaat
        cursor.execute("PRAGMA table_info(prompts)")
        columns = [row[1] for row in cursor.fetchall()]
        if "voice" not in columns:
            print("Kolom 'voice' wordt toegevoegd...")
            cursor.execute("ALTER TABLE prompts ADD COLUMN voice TEXT")     
        else:
            print("Kolom 'voice' bestaat al.")

        # Optioneel: vul voice in voor bekende profielen
        default_voices = {
            "default": "George",
            "obsidian": "Martin_int",
            "code": "Frank"
}

        for profile, voice in default_voices.items():
            cursor.execute(
                "UPDATE prompts SET voice = ? WHERE prompt_name = ?",       
                (voice, profile)
)

        conn.commit()
        print("Voice-kolom toegevoegd en standaardwaarden ingevuld.")       
        conn.close()

    except Exception as e:
        print("Fout bij aanpassen van database:", e)

if __name__ == "__main__":
    add_voice_column_and_fill()