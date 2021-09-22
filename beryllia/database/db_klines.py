from dataclasses import dataclass
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from ipaddress   import IPv4Network, IPv6Network
from typing      import List, Optional, Union

from .common     import Table
from ..normalise import SearchType
from ..util      import glob_to_sql

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
        query = """
            SELECT mask, source, oper, duration, reason, ts, expire
            FROM kline
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)

        if row is not None:
            return DBKLine(*row)
        else:
            return None

    async def find(self, mask: str) -> Optional[int]:
        query = """
            SELECT kline.id FROM kline

            LEFT JOIN kline_remove
            ON  kline.id = kline_remove.kline_id
            AND kline_remove.ts IS NULL

            WHERE kline.mask = $1
            AND kline.expire > NOW()

            ORDER BY kline.id DESC
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, mask)

    async def add(self,
            source:   str,
            oper:     str,
            mask:     str,
            duration: int,
            reason:   str) -> int:

        utcnow = datetime.utcnow()
        query  = """
            INSERT INTO kline
            (mask, source, oper, duration, reason, ts, expire)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        args = [
            mask,
            source,
            oper,
            duration,
            reason,
            utcnow,
            utcnow + timedelta(seconds=duration)
        ]
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

        return await self.find(mask) or -1 # -1 to fix typehint

class KLineRemoveTable(Table):
    async def add(self,
            id:     int,
            source: Optional[str],
            oper:   Optional[str]):

        query = """
            INSERT INTO kline_remove (kline_id, source, oper, ts)
            VALUES ($1, $2, $3, NOW()::TIMESTAMP)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, id, source, oper)

    async def get(self, id: int) -> Optional[DBKLineRemove]:
        query = """
            SELECT source, oper, ts
            FROM kline_remove
            WHERE kline_id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)

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
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW()::timestamp)
        """
        args = [
            nickname,
            self.to_search(nickname, SearchType.NICK),
            username,
            self.to_search(username, SearchType.USER),
            hostname,
            self.to_search(hostname, SearchType.HOST),
            ip,
            kline_id
        ]
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    async def get(self, id: int) -> Optional[DBKLineKill]:
        query = """
            SELECT kline_id, nickname, username, hostname, ip, ts
            FROM kline_kill
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)

        if row is not None:
            return DBKLineKill(*row)
        else:
            return None

    async def find_by_nick(self, nickname: str) -> List[int]:
        query = """
            SELECT id
            FROM kline_kill
            WHERE search_nick LIKE $1
            ORDER BY ts DESC
        """
        param = self.to_search(glob_to_sql(nickname), SearchType.NICK)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, param)

        return [row[0] for row in rows]

    async def find_by_host(self, hostname: str) -> List[int]:
        query = """
            SELECT id
            FROM kline_kill
            WHERE search_host LIKE $1
            ORDER BY ts DESC
        """
        param = self.to_search(glob_to_sql(hostname), SearchType.HOST)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, param)

        return [row[0] for row in rows]

    async def find_by_ip(self,
            ip: Union[IPv4Address, IPv6Address]
            ) -> List[int]:

        query = """
            SELECT id
            FROM kline_kill
            WHERE ip = $1
            ORDER BY ts DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, ip)

        return [row[0] for row in rows]

    async def find_by_cidr(self,
            cidr: Union[IPv4Network, IPv6Network]
            ) -> List[int]:

        query = """
            SELECT id
            FROM kline_kill
            WHERE ip << $1
            ORDER BY ts DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, cidr)
        return [row[0] for row in rows]

    async def find_by_ip_glob(self, glob: str) -> List[int]:
        query  = """
            SELECT id
            FROM kline_kill
            WHERE TEXT(ip) LIKE $1
            ORDER BY ts DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, glob_to_sql(glob))
        return [row[0] for row in rows]


    async def find_by_kline(self, kline_id: int) -> List[int]:
        query = """
            SELECT id
            FROM kline_kill
            WHERE kline_id = $1
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, kline_id)

        return [row[0] for row in rows]

    async def set_kline(self,
            kill_id:  int,
            kline_id: int):

        query = """
            UPDATE kline_kill
            SET kline_id = $1
            WHERE id = $2
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, kline_id, kill_id)
