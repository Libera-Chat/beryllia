from .common import Table
from ..normalise import SearchType

class KLineChanTagTable(Table):
    async def add(self, klinechan_id: int, tag: str, soper: str) -> None:
        query = """
            INSERT INTO klinechan_tag (klinechan_id, tag, search_tag, soper, ts)
            VALUES ($1, $2, $3, $4, NOW()::TIMESTAMP)
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query, klinechan_id, tag, str(self.to_search(tag, SearchType.TAG)), soper
            )

    async def exists(self, klinechan_id: int, tag: str) -> bool:
        query = """
            SELECT 1 FROM klinechan_tag
            WHERE klinechan_id = $1
            AND search_tag = $2
        """

        async with self.pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    query, klinechan_id, str(self.to_search(tag, SearchType.TAG))
                )
            )
