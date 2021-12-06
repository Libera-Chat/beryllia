from dataclasses import dataclass
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from ipaddress   import IPv4Network, IPv6Network
from typing      import (Any, Collection, Dict, Optional, Sequence, Tuple,
    Union)

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

    async def exists(self, id: int) -> bool:
        query = """
            SELECT 1
                FROM kline
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            return bool(await conn.fetchval(query, id))

    async def list_active(self) -> Dict[str, int]:
        query = """
            SELECT kline.mask, kline.id FROM kline

            LEFT JOIN kline_remove
            ON kline.id = kline_remove.kline_id

            WHERE kline_remove.ts IS NULL
            AND kline.expire > NOW()::TIMESTAMP
        """
        async with self.pool.acquire() as conn:
            return dict(await conn.fetch(query))

    async def find_active(self, mask: str) -> Optional[int]:
        query = """
            SELECT kline.id FROM kline

            LEFT JOIN kline_remove
            ON  kline.id = kline_remove.kline_id
            AND kline_remove.ts IS NULL

            WHERE kline.mask = $1
            AND kline.expire > NOW()

            ORDER BY kline.ts DESC
            LIMIT 1
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
            RETURNING id
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
            return await conn.fetchval(query, *args)


    async def find_by_ts(self,
            ts:    datetime,
            fudge: int = 1
            ) -> Collection[Tuple[int, datetime]]:

        query = """
            SELECT id, ts FROM kline
            WHERE ABS(
                EXTRACT(
                    EPOCH FROM (
                        DATE_TRUNC('minute', ts) - $1
                    )
                )
            ) / 60 <= $2
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, ts, fudge)

    async def find_last_by_oper(self, oper: str, count: int) -> Sequence[int]:
        query = """
            SELECT id FROM kline
            WHERE oper = $1
            ORDER BY ts DESC
            LIMIT $2
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, oper, count)
        return [r[0] for r in rows]
