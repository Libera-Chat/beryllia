from .common import Table

class KLineChanTable(Table):
    async def add(self, channel: str, soper: str, reason: str) -> int:
        query = """
            INSERT INTO klinechan (channel, soper, reason, ts)
            VALUES ($1, $2, $3, NOW()::TIMESTAMP)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, channel, soper, reason)
