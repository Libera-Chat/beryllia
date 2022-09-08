from .common import Table
from ..normalise import SearchType


class CloseTagTable(Table):
    async def add(self, close_id: int, tag: str, soper: str) -> None:

        query = """
            INSERT INTO close_tag (close_id, tag, search_tag, soper, ts)
            VALUES ($1, $2, $3, $4, NOW()::TIMESTAMP)
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query, close_id, tag, str(self.to_search(tag, SearchType.TAG)), soper
            )

    async def exists(self, close_id: int, tag: str) -> bool:
        query = """
            SELECT 1 FROM close_tag
            WHERE close_id = $1
            AND search_tag = $2
        """

        async with self.pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    query, close_id, str(self.to_search(tag, SearchType.TAG))
                )
            )
