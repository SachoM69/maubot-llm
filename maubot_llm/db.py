from mautrix.util.async_db import UpgradeTable, Connection, Database
from typing import Optional, List
from mautrix.types.primitive import RoomID

upgrade_table = UpgradeTable()


@upgrade_table.register(description="v1")
async def upgrade_v1(conn: Connection) -> None:
    await conn.execute(
        """CREATE TABLE rooms (
            id TEXT NOT NULL PRIMARY KEY,
            backend TEXT,
            model TEXT,
            system_prompt TEXT
        )"""
    )
    await conn.execute(
        """CREATE TABLE context_entries (
          room_id TEXT NOT NULL,
          seq_num INTEGER NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          PRIMARY KEY (room_id, seq_num),
          FOREIGN KEY (room_id) REFERENCES rooms(id)
        )"""
    )


class Room:
    def __init__(self, room_id) -> None:
        self.room_id = room_id
        self.backend = None
        self.model = None
        self.system_prompt = None

    room_id: RoomID
    backend: Optional[str]
    model: Optional[str]
    system_prompt: Optional[str]


async def fetch_room(db: Database, room_id: RoomID) -> Optional[Room]:
    q = "SELECT id, backend, model, system_prompt FROM rooms WHERE id=$1"
    row = await db.fetchrow(q, room_id)
    if not row:
        return None
    room = Room(room_id)
    room.backend = row["backend"]
    room.model = row["model"]
    room.system_prompt = row["system_prompt"]
    return room


async def upsert_room(db: Database, room: Room) -> None:
    q = """
        INSERT INTO rooms(id, backend, model, system_prompt) VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO UPDATE SET backend=excluded.backend, model=excluded.model, system_prompt=excluded.system_prompt
    """
    await db.execute(q, room.room_id, room.backend, room.model, room.system_prompt)


async def fetch_context(db: Database, room_id: RoomID) -> List[dict]:
    q = "SELECT role, content FROM context_entries WHERE room_id=$1 ORDER BY seq_num"
    rows = await db.fetch(q, room_id)
    return [{"role": row["role"], "content": row["content"]} for row in rows]


async def append_context(db: Database, room_id: RoomID, role: str, content: str) -> None:
    q = """
        INSERT INTO context_entries(room_id, seq_num, role, content)
        VALUES ($1, (SELECT COALESCE(MAX(seq_num),0)+1 FROM context_entries WHERE room_id=$1), $2, $3)
    """
    await db.execute(q, room_id, role, content)


async def clear_context(db: Database, room_id: RoomID) -> None:
    q = "DELETE FROM context_entries WHERE room_id=$1"
    await db.execute(q, room_id)
