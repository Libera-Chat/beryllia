from dataclasses import dataclass
from datetime    import datetime, timedelta
from ipaddress   import IPv4Address, IPv6Address
from ipaddress   import IPv4Network, IPv6Network
from typing      import Any, Collection, Optional, Tuple, Union

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
