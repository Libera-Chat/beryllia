from dataclasses import dataclass
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from typing      import List, Optional, Union

from .common     import Table
from ..normalise import SearchType

@dataclass
class DBKLine(object):
    mask:     str
    source:   str
    oper:     str
    duration: int
    reason:   str
    ts:       datetime
    expire:   datetime

@dataclass
class DBKLineKill(object):
    kline_id: int
    nickname: str
    username: str
    hostname: str
    ip:       Optional[Union[IPv4Address, IPv6Address]]
    ts:       datetime

@dataclass
class DBKLineRemove(object):
    source: str
    oper:   str
    ts:     datetime

class KLineTable(Table):
    async def get(self, id: int) -> Optional[DBKLine]:
        row = await self.connection.fetchrow("""
            SELECT mask, source, oper, duration, reason, ts, expire
            FROM kline
            WHERE id = $1
        """, id)
        if row is not None:
            return DBKLine(*row)
        else:
            return None

    async def find(self, mask: str) -> Optional[int]:
        return await self.connection.fetchval("""
            SELECT kline.id FROM kline

            LEFT JOIN kline_remove
            ON  kline.id = kline_remove.kline_id
            AND kline_remove.ts IS NULL

            WHERE kline.mask = $1
            AND kline.expire > $2

            ORDER BY kline.id DESC
        """, mask, datetime.utcnow())

    async def add(self,
            source:   str,
            oper:     str,
            mask:     str,
            duration: int,
            reason:   str) -> int:

        ts_now = datetime.utcnow()

        sql = """
            INSERT INTO kline
            (mask, source, oper, duration, reason, ts, expire)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        await self.connection.execute(
            sql,
            mask,
            source,
            oper,
            duration,
            reason,
            ts_now,
            ts_now + timedelta(seconds=duration)
        )

        return await self.find(mask) or -1 # -1 to fix typehint


class KLineRemoveTable(Table):
    async def add(self,
            id:     int,
            source: Optional[str],
            oper:   Optional[str]):

        await self.connection.execute("""
            INSERT INTO kline_remove (kline_id, source, oper, ts)
            VALUES ($1, $2, $3, $4)
        """, id, source, oper, datetime.utcnow())

    async def get(self, id: int) -> Optional[DBKLineRemove]:
        row = await self.connection.fetchrow("""
            SELECT source, oper, ts
            FROM kline_remove
            WHERE kline_id = $1
        """, id)
        if row is not None:
            return DBKLineRemove(*row)
        else:
            return None

class KLineKillTable(Table):
    async def add(self,
            kline_id: int,
            nickname: str,
            username: str,
            hostname: str,
            ip:       Optional[Union[IPv4Address, IPv6Address]]):

        query = """
            INSERT INTO kline_kill (
                nickname,
                search_nick,
                username,
                search_user,
                hostname,
                search_host,
                ip,
                kline_id,
                ts
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """
        await self.connection.execute(
            query,
            nickname,
            self.to_search(nickname, SearchType.NICK),
            username,
            self.to_search(username, SearchType.USER),
            hostname,
            self.to_search(hostname, SearchType.HOST),
            ip,
            kline_id,
            datetime.utcnow()
        )

    async def get(self, id: int) -> Optional[DBKLineKill]:
        row = await self.connection.fetchrow("""
            SELECT kline_id, nickname, username, hostname, ip, ts
            FROM kline_kill
            WHERE id = $1
        """, id)
        if row is not None:
            return DBKLineKill(*row)
        else:
            return None

    async def find_by_nick(self, search_nick: str) -> List[int]:
        rows = await self.connection.fetch("""
            SELECT id
            FROM kline_kill
            WHERE search_nick = $1
            ORDER BY ts DESC
        """, search_nick)
        return [row[0] for row in rows]

    async def find_by_host(self, search_host: str) -> List[int]:
        rows = await self.connection.fetch("""
            SELECT id
            FROM kline_kill
            WHERE search_host = $1
            ORDER BY ts DESC
        """, search_host)
        return [row[0] for row in rows]

    async def find_by_ip(self, ip: str) -> List[int]:
        rows = await self.connection.fetch("""
            SELECT id
            FROM kline_kill
            WHERE ip = $1
            ORDER BY ts DESC
        """, ip)
        return [row[0] for row in rows]

    async def find_by_kline(self, kline_id: int) -> List[int]:
        rows = await self.connection.fetch("""
            SELECT id
            FROM kline_kill
            WHERE kline_id = $1
        """, kline_id)
        return [row[0] for row in rows]

    async def set_kline(self,
            kill_id:  int,
            kline_id: int):

        await db.execute("""
            UPDATE kline_kill
            SET kline = $1
            WHERE id = $2
        """, kline_id, kill_id)
