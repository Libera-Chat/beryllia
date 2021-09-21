from collections import OrderedDict
from datetime    import datetime
from typing      import OrderedDict as TOrderedDict

from .common     import Table

class StatsPTable(Table):
    async def add(self,
            oper: str,
            mask: str,
            ts:   datetime):

        await self.connection.execute("""
            INSERT INTO statsp (oper, mask, ts)
            VALUES ($1, $2, $3)
        """, oper, mask, ts)

    async def count_since(self,
            ts: datetime
            ) -> TOrderedDict[str, int]:

        rows = await self.connection.fetch("""
            SELECT oper, COUNT(*) AS minutes
            FROM statsp
            WHERE ts >= $1
            GROUP BY oper
            ORDER BY minutes DESC
        """, ts)
        return OrderedDict(rows)
