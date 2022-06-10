from .common import Table


class FreezeTable(Table):
    async def add(self, account: str, soper: str, reason: str) -> int:

        query = """
            INSERT INTO "freeze" (account, soper, reason, ts)
            VALUES ($1, $2, $3, NOW()::TIMESTAMP)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, account, soper, reason)
