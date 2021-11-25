from datetime    import datetime
from typing      import Sequence, Tuple

from .common     import Table
from ..normalise import SearchType
from ..util      import glob_to_sql, lex_glob_pattern

class NickChangeTable(Table):
    async def add(self, cliconn_id: int, nickname: str):
        query = """
            INSERT INTO nick_change (cliconn_id, nickname, search_nick, ts)
            VALUES ($1, $2, $3, NOW()::TIMESTAMP)
        """
        args = [
            cliconn_id,
            nickname,
            str(self.to_search(nickname, SearchType.NICK)),
        ]

        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    async def find_cliconn(self,
            nickname: str
            ) -> Sequence[Tuple[int, datetime]]:

        query = """
            SELECT cliconn.id, cliconn.ts
                FROM cliconn
            INNER JOIN nick_change
                ON cliconn.id = nick_change.cliconn_id
                AND nick_change.search_nick LIKE $1;
        """

        pattern = glob_to_sql(lex_glob_pattern(nickname))
        param   = str(self.to_search(pattern, SearchType.NICK))
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, param)
