from .common import Table
from ..normalise import SearchType


class FreezeTagTable(Table):
    async def add(self, freeze_id: int, tag: str, soper: str) -> None:

        query = """
            INSERT INTO freeze_tag (freeze_id, tag, search_tag, soper, ts)
            VALUES ($1, $2, $3, $4, NOW()::TIMESTAMP)
        """

        async with self.pool.acquire() as conn:
            await conn.execute(
                query, freeze_id, tag, str(self.to_search(tag, SearchType.TAG)), soper
            )

    async def exists(self, freeze_id: int, tag: str) -> bool:
        query = """
            SELECT 1 FROM freeze_tag
            WHERE freeze_id = $1
            AND search_tag = $2
        """

        async with self.pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    query, freeze_id, str(self.to_search(tag, SearchType.TAG))
                )
            )
