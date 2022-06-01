import json
from typing import Any, Optional
from .common import Table


class PreferenceTable(Table):
    async def get(self, oper: str, key: str) -> Optional[Any]:
        query = """
            SELECT value
            FROM preference
            WHERE oper = $1
            AND key = $2
        """
        async with self.pool.acquire() as conn:
            value = await conn.fetchval(query, oper, key)

        if value is not None:
            return json.loads(value)
        else:
            return value

    async def set(self, oper: str, key: str, value: Any):
        if await self.get(oper, key) is None:
            query = """
                INSERT INTO preference (oper, key, value)
                VALUES ($1, $2, $3)
            """
        else:
            query = """
                UPDATE preference
                SET value = $3
                WHERE oper = $1
                AND key = $2
            """

        async with self.pool.acquire() as conn:
            await conn.execute(query, oper, key, json.dumps(value))
