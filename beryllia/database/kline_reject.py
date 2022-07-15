from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Collection, Optional, Sequence, Tuple, Union

from .kline_kill import DBKLineKill, KLineKillTable
from ..normalise import SearchType


class DBKLineReject(DBKLineKill):
    pass


class KLineRejectTable(KLineKillTable):
    async def add(
        self,
        kline_id: int,
        nickname: str,
        username: str,
        hostname: str,
        ip: Optional[Union[IPv4Address, IPv6Address]],
    ):

        query = """
            INSERT INTO kline_reject (
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
            kline_id,
        ]
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    async def find(
        self,
        kline_id: int,
        nickname: str,
        username: str,
        hostname: str,
        ip: Optional[Union[IPv4Address, IPv6Address]],
    ) -> Optional[int]:

        query = """
            SELECT id FROM kline_reject
            WHERE kline_id  = $1
            AND search_nick = $2
            AND search_user = $3
            AND search_host = $4
            AND ip          = $5
        """
        args = [
            kline_id,
            str(self.to_search(nickname, SearchType.NICK)),
            str(self.to_search(username, SearchType.USER)),
            str(self.to_search(hostname, SearchType.HOST)),
            ip,
        ]
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def _find_klines(
        self, where: str, args: Sequence[Any], count: int
    ) -> Collection[Tuple[int, datetime]]:

        query = f"""
            SELECT kline.id, MIN(kline.ts) AS kline_ts
                FROM kline_reject
            INNER JOIN kline
                ON kline_reject.kline_id = kline.id
            {where}
            GROUP BY kline.id
            ORDER BY kline_ts DESC
            LIMIT {count}
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)

        return rows

    async def find_by_kline(self, kline_id: int) -> Collection[DBKLineReject]:
        query = """
            SELECT id, nickname, username, hostname, ip, ts
            FROM kline_reject
            WHERE kline_id = $1
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, kline_id)

        return [DBKLineReject(*row) for row in rows]

    async def find_by_hostname(self, kline_id: int, hostname: str) -> Collection[int]:

        query = """
            SELECT id
            FROM kline_reject
            WHERE kline_id = $1
            AND search_host = $2
        """
        search_host = str(self.to_search(hostname, SearchType.HOST))
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, kline_id, search_host)
        return [r[0] for r in rows]

    async def set_kline(self, reject_id: int, kline_id: int):

        query = """
            UPDATE kline_reject
            SET kline_id = $1
            WHERE id = $2
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, kline_id, reject_id)
