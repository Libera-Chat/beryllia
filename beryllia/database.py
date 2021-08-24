import time
from dataclasses import dataclass
from typing      import List, Optional, Tuple
import aiosqlite

# schema, also in make-database.sql
#
# klines:
#   id:        int, incremental
#   mask:      str, not null
#   setter:    str, not null
#   duration:  int, not null
#   reason:    str, not null
#   ts:        int, not null
#   remove_at: int
#   remove_by: str
# kills:
#   nickname: str, not null
#   username: str, not null
#   hostname: str, not null
#   ip:       str, not null
#   ts:       int, not null
#   kline_id: int, foreign key klines.id, nullable

#TODO: don't open the database for every operation

@dataclass
class DBKLine(object):
    mask:      str
    setter:    str
    duration:  int
    reason:    str
    ts:        int
    remove_at: Optional[int]
    remove_by: Optional[str]

class Database(object):
    def __init__(self, location: str):
        self._location = location

    async def get_kline(self, id: int) -> Optional[DBKLine]:
        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT mask, setter, duration, reason, ts, remove_at, remove_by
                FROM klines
                WHERE id=?
            """, [id])
            row = await cursor.fetchone()
            if row is not None:
                return DBKLine(*row)
            else:
                return None

    async def find_kline(self, mask: str) -> Optional[int]:
        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT id FROM klines
                WHERE mask=? AND
                remove_at IS NULL
                ORDER BY id DESC
            """, [mask])
            row = await cursor.fetchone()
            if row is not None:
                return row[0]
            else:
                return None

    async def list_klines(self) -> List:
        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT id,mask FROM klines
                WHERE remove_at IS NULL
                ORDER BY id DESC
            """)
            results = await cursor.fetchall()
            if results is not None:
                return {mask: id for id, mask in results}
            else:
                return None

    async def del_kline(self,
            id:      int,
            remover: Optional[str]):

        async with aiosqlite.connect(self._location) as db:
            await db.execute("""
                UPDATE klines
                SET remove_by=?,remove_at=?
                WHERE id=?
            """, [remover, int(time.time()), id])
            await db.commit()

    async def add_kline(self,
            setter:   str,
            mask:     str,
            duration: int,
            reason:   str) -> int:

        async with aiosqlite.connect(self._location) as db:
            await db.execute("""
                INSERT INTO klines (mask, setter, duration, reason, ts)
                VALUES (?, ?, ?, ?, ?)
            """, [mask, setter, duration, reason, int(time.time())])
            await db.commit()

        return await self.find_kline(mask) or -1 # -1 to fix typehint

    async def add_kill(self,
            nickname: str,
            username: str,
            hostname: str,
            ip:       str,
            kline_id: Optional[int]):

        async with aiosqlite.connect(self._location) as db:
            await db.execute("""
                INSERT INTO kills (nickname, username, hostname, ip, kline_id, ts)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [nickname, username, hostname, ip, kline_id, int(time.time())])
            await db.commit()

    async def find_kills_by_nick(self,
            nickname: str
            ) -> List[Tuple[str, str, str, int, Optional[int]]]:

        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT nickname, username, hostname, ts, kline_id
                FROM kills
                WHERE nickname=?
                ORDER BY ts DESC
            """, [nickname])
            return await cursor.fetchall()

    async def find_kills_by_host(self,
            hostname: str
            ) -> List[Tuple[str, str, str, int, Optional[int]]]:

        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT nickname, username, hostname, ts, kline_id
                FROM kills
                WHERE hostname=?
                ORDER BY ts DESC
            """, [hostname])
            return await cursor.fetchall()

    async def find_kills_by_ip(self,
            ip: str
            ) -> List[Tuple[str, str, str, int, Optional[int]]]:

        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT nickname, username, hostname, ts, kline_id
                FROM kills
                WHERE ip=?
                ORDER BY ts DESC
            """, [ip])
            return await cursor.fetchall()
