from .common     import Table
from ..normalise import SearchType

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
