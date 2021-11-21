from dataclasses import dataclass
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from ipaddress   import IPv4Network, IPv6Network
from typing      import Any, Optional, Sequence, Union

from .common     import Table
from ..normalise import SearchType
from ..util      import lex_glob_pattern, glob_to_sql

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
    id:       int
    nickname: str
    username: str
    hostname: str
    ip:       Optional[Union[IPv4Address, IPv6Address]]
    ts:       datetime

    # nick user host
    def nuh(self) -> str:
        return f"{self.nickname}!{self.username}@{self.hostname}"

@dataclass
class DBKLineRemove(object):
    source: str
    oper:   str
    ts:     datetime

class KLineTable(Table):
    async def get(self, id: int) -> DBKLine:
        query = """
            SELECT mask, source, oper, duration, reason, ts, expire
            FROM kline
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)

        return DBKLine(*row)

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
            str(self.to_search(nickname, SearchType.NICK)),
            username,
            str(self.to_search(username, SearchType.USER)),
            hostname,
            str(self.to_search(hostname, SearchType.HOST)),
            ip,
            kline_id
        ]
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    async def _get_kline(self,
            where: str,
            limit: Optional[int],
            *args: Any
            ) -> Sequence[int]:

        limit_str = ""
        if limit is not None:
            limit_str = f"LIMIT {limit}"

        query = f"""
            SELECT DISTINCT(kline.id), kline.ts FROM kline_kill
            LEFT JOIN kline ON kline_kill.kline_id = kline.id
            {where}
            ORDER BY kline.ts desc
            {limit_str}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)

        return [row[0] for row in rows]

    async def find_by_nick(self,
            nickname: str,
            limit:    Optional[int]=None
            ) -> Sequence[int]:

        pattern = glob_to_sql(lex_glob_pattern(nickname))
        param   = str(self.to_search(pattern, SearchType.NICK))
        return await self._get_kline(
            "WHERE search_nick LIKE $1", limit, param
        )

    async def find_by_host(self,
            hostname: str,
            limit:    Optional[int]=None
            ) -> Sequence[int]:

        pattern = glob_to_sql(lex_glob_pattern(hostname))
        param   = str(self.to_search(pattern, SearchType.HOST))
        return await self._get_kline(
            "WHERE search_host LIKE $1", limit, param
        )

    async def find_by_ip(self,
            ip:    Union[IPv4Address, IPv6Address],
            limit: Optional[int]=None
            ) -> Sequence[int]:

        return await self._get_kline("WHERE ip = $1", limit, ip)

    async def find_by_cidr(self,
            cidr:  Union[IPv4Network, IPv6Network],
            limit: Optional[int]=None
            ) -> Sequence[int]:

        return await self._get_kline("WHERE ip << $1", limit, cidr)

    async def find_by_ip_glob(self,
            glob:  str,
            limit: Optional[int]=None
            ) -> Sequence[int]:

        pattern = glob_to_sql(lex_glob_pattern(glob))
        param   = str(self.to_search(pattern, SearchType.HOST))
        return await self._get_kline("WHERE TEXT(ip) LIKE $1", limit, param)

    async def find_by_kline(self,
            kline_id: int
            ) -> Sequence[DBKLineKill]:
        query = """
            SELECT id, nickname, username, hostname, ip, ts
            FROM kline_kill
            WHERE kline_id = $1
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, kline_id)

        return [DBKLineKill(*row) for row in rows]

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
