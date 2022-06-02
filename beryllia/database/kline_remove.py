from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .common import Table


@dataclass
class DBKLineRemove(object):
    source: str
    oper: str
    ts: datetime


class KLineRemoveTable(Table):
    async def add(self, id: int, source: Optional[str], oper: Optional[str]):

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
