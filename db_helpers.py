import aiosqlite

# --- Specifiek voor modi ---
async def init_modes_table(db_path: str):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS modes (
                name TEXT PRIMARY KEY)""")
        await db.commit()

async def list_modes(db_path: str) -> list[str]:
    await init_modes_table(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT name FROM modes ORDER BY name")   
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def add_mode(name: str, db_path: str):
    await init_modes_table(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("INSERT OR IGNORE INTO modes (name) VALUES (?)", (name,))
        await db.commit()

async def delete_mode(name: str, db_path: str):
    await init_modes_table(db_path)
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM modes WHERE name = ?", (name,))       
        await db.commit()