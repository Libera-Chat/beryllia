from collections import OrderedDict
from datetime import datetime
from typing import OrderedDict as TOrderedDict

from .common import Table


class StatsPTable(Table):
    async def add(self, oper: str, mask: str, ts: datetime):

        query = """
            INSERT INTO statsp (oper, mask, ts)
            VALUES ($1, $2, $3)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, oper, mask, ts)

    async def count_since(self, ts: datetime) -> TOrderedDict[str, int]:

        query = """
            SELECT oper, COUNT(*) AS minutes
            FROM statsp
            WHERE ts >= $1
            GROUP BY oper
            ORDER BY minutes DESC
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, ts)

        return OrderedDict(rows)
