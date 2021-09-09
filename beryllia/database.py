import time
from dataclasses import dataclass
from typing      import List, Optional, Tuple
import aiosqlite

# schema, also in make-database.sql
#
# klines:
#   id:        int, incremental
#   mask:      str, not null
#   source:    str, not null
#   oper:      str, not null
#   duration:  int, not null
#   reason:    str, not null
#   ts:        int, not null
# kline_removes:
#   id:     int, foreign key klines.id
#   source: str, nullable
#   oper:   str, nullable
#   ts:     int, not null
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
    mask:     str
    source:   str
    oper:     str
    duration: int
    reason:   str
    ts:       int

@dataclass
class DBKlineRemove(object):
    source: str
    oper:   str
    ts:     int

class Database(object):
    def __init__(self, location: str):
        self._location = location

    async def get_kline(self, id: int) -> Optional[DBKLine]:
        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT mask, source, oper, duration, reason, ts
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
                SELECT klines.id FROM klines

                LEFT JOIN kline_removes
                ON klines.id = kline_removes.id

                WHERE mask=? AND
                kline_removes.ts IS NULL

                ORDER BY klines.id DESC
            """, [mask])
            row = await cursor.fetchone()
            if row is not None:
                return row[0]
            else:
                return None

    async def get_remove(self, id: int) -> Optional[DBKlineRemove]:
        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT source, oper, ts
                FROM kline_removes
                WHERE id=?
            """, [id])
            row = await cursor.fetchone()
            if row is not None:
                return DBKlineRemove(*row)
            else:
                return None

    async def del_kline(self,
            id:     int,
            source: Optional[str],
            oper:   Optional[str]):

        async with aiosqlite.connect(self._location) as db:
            await db.execute("""
                INSERT INTO kline_removes (id, source, oper, ts)
                VALUES (?, ?, ?, ?)
            """, [id, source, oper, int(time.time())])
            await db.commit()

    async def add_kline(self,
            source:   str,
            oper:     str,
            mask:     str,
            duration: int,
            reason:   str) -> int:

        async with aiosqlite.connect(self._location) as db:
            await db.execute("""
                INSERT INTO klines (mask, source, oper, duration, reason, ts)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [mask, source, oper, duration, reason, int(time.time())])
            await db.commit()

        return await self.find_kline(mask) or -1 # -1 to fix typehint

    async def add_kill(self,
            nickname:    str,
            search_nick: str,
            username:    str,
            search_user: str,
            hostname:    str,
            search_host: str,
            ip:          str,
            kline_id:    Optional[int]):

        async with aiosqlite.connect(self._location) as db:
            await db.execute("""
                INSERT INTO kills (
                    nickname, search_nick,
                    username, search_user,
                    hostname, search_host,
                    ip,
                    kline_id,
                    ts
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                nickname, search_nick,
                username, search_user,
                hostname, search_host,
                ip,
                kline_id,
                int(time.time())
            ])
            await db.commit()

    async def find_kills_by_nick(self,
            nickname: str
            ) -> List[Tuple[str, str, str, int, Optional[int]]]:

        async with aiosqlite.connect(self._location) as db:
            cursor = await db.execute("""
                SELECT nickname, username, hostname, ts, kline_id
                FROM kills
                WHERE search_nick=?
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
                WHERE search_host=?
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
