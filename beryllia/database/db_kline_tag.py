from datetime import datetime
from typing import Collection, Tuple

from .common import Table
from ..normalise import SearchType
from ..util import glob_to_sql, lex_glob_pattern


class KLineTagTable(Table):
    async def add(self, kline_id: int, tag: str, source: str, oper: str):

        query = """
            INSERT INTO kline_tag
                (kline_id, tag, search_tag, source, oper, ts)
            VALUES ($1, $2, $3, $4, $5, NOW()::TIMESTAMP)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                kline_id,
                tag,
                str(self.to_search(tag, SearchType.TAG)),
                source,
                oper,
            )

    async def remove(self, kline_id: int, tag: str):
        query = """
            DELETE FROM kline_tag
            WHERE kline_id = $1
            AND search_tag = $2
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query, kline_id, str(self.to_search(tag, SearchType.TAG))
            )

    async def exists(self, kline_id: int, tag: str) -> bool:
        query = """
            SELECT 1 FROM kline_tag
            WHERE kline_id = $1
            AND search_tag = $2
        """

        async with self.pool.acquire() as conn:
            return bool(
                await conn.fetchval(
                    query, kline_id, str(self.to_search(tag, SearchType.TAG))
                )
            )

    async def find(self, tag: str) -> Collection[Tuple[int, datetime]]:
        query = """
            SELECT DISTINCT(kline.id), kline.ts
                FROM kline_tag
            INNER JOIN kline
                ON kline_tag.kline_id = kline.id
            WHERE kline_tag.search_tag LIKE $1
        """
        pattern = glob_to_sql(lex_glob_pattern(tag))
        param = str(self.to_search(pattern, SearchType.TAG))
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, param)
