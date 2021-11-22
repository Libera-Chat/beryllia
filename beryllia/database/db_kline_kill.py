from dataclasses import dataclass
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from ipaddress   import IPv4Network, IPv6Network
from typing      import Any, Collection, Optional, Tuple, Union

from .common     import NickUserHost, Table
from ..normalise import SearchType
from ..util      import lex_glob_pattern, glob_to_sql

@dataclass
class DBKLineKill(NickUserHost):
    id:       int
    nickname: str
    username: str
    hostname: str
    ip:       Optional[Union[IPv4Address, IPv6Address]]
    ts:       datetime

    # nick user host
    def nuh(self) -> str:
        return f"{self.nickname}!{self.username}@{self.hostname}"

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

    async def _find_klines(self,
            where: str,
            *args: Any
            ) -> Collection[Tuple[int, datetime]]:

        query = f"""
            SELECT DISTINCT(kline.id), kline.ts
            FROM kline_kill
            INNER JOIN kline
            ON kline_kill.kline_id = kline.id
            {where}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)

        return rows

    async def find_by_nick(self,
            nickname: str
            ) -> Collection[Tuple[int, datetime]]:

        pattern = glob_to_sql(lex_glob_pattern(nickname))
        param   = str(self.to_search(pattern, SearchType.NICK))
        return await self._find_klines("WHERE search_nick LIKE $1", param)

    async def find_by_host(self,
            hostname: str
            ) -> Collection[Tuple[int, datetime]]:

        pattern = glob_to_sql(lex_glob_pattern(hostname))
        param   = str(self.to_search(pattern, SearchType.HOST))
        return await self._find_klines("WHERE search_host LIKE $1", param)

    async def find_by_ip(self,
            ip:    Union[IPv4Address, IPv6Address]
            ) -> Collection[Tuple[int, datetime]]:

        return await self._find_klines("WHERE ip = $1", ip)

    async def find_by_cidr(self,
            cidr:  Union[IPv4Network, IPv6Network]
            ) -> Collection[Tuple[int, datetime]]:

        return await self._find_klines("WHERE ip << $1", cidr)

    async def find_by_ip_glob(self,
            glob:  str
            ) -> Collection[Tuple[int, datetime]]:

        pattern = glob_to_sql(lex_glob_pattern(glob))
        param   = str(self.to_search(pattern, SearchType.HOST))
        return await self._find_klines("WHERE TEXT(ip) LIKE $1", param)

    async def find_by_kline(self,
            kline_id: int
            ) -> Collection[DBKLineKill]:
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
