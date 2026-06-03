import unittest
from pathlib import Path
from mautrix.util.async_db import Database
from maubot_llm.db import upgrade_table, fetch_room, upsert_room, Room, fetch_context, append_context, clear_context

DB_PATH = Path("test.sqlite3")
DB_FILES = [DB_PATH, Path("test.sqlite3-shm"), Path("test.sqlite3-wal")]
DB_URI = f"sqlite:///{DB_PATH.resolve()}"


class TestDb(unittest.IsolatedAsyncioTestCase):
    async def test_basics(self) -> None:
        db = Database.create(DB_URI, upgrade_table=upgrade_table)
        await db.start()
        try:
            self.assertEqual(None, await fetch_room(db, "a"))
            
            room = Room("a")
            await upsert_room(db, room)
            room = await fetch_room(db, "a")
            self.assertIsNotNone(room)
            self.assertEqual("a", room.room_id)
            self.assertEqual(None, room.backend)
            self.assertEqual(None, room.model)
            self.assertEqual(None, room.system_prompt)

            room.backend = "potato"
            room.model = "rng"
            room.system_prompt = "you are confused"
            await upsert_room(db, room)
            self.assertEqual("a", room.room_id)
            self.assertEqual("potato", room.backend)
            self.assertEqual("rng", room.model)
            self.assertEqual("you are confused", room.system_prompt)

            self.assertEqual(None, await fetch_room(db, "b"))

            self.assertEqual([], await fetch_context(db, "a"))
            
            await append_context(db, "a", "user", "Please tell me why?")
            self.assertEqual([
                {"role": "user", "content": "Please tell me why?"}
            ], await fetch_context(db, "a"))

            await append_context(db, "a", "assistant", "no")
            self.assertEqual([
                {"role": "user", "content": "Please tell me why?"},
                {"role": "assistant", "content": "no"}
            ], await fetch_context(db, "a"))

            self.assertEqual([], await fetch_context(db, "b"))
            
            await clear_context(db, "a")
            self.assertEqual([], await fetch_context(db, "a"))
        finally:
            await db.stop()
            for path in DB_FILES:
                if path.exists():
                    path.unlink()


if __name__ == "__main__":
    unittest.main()
