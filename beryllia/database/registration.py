from .common import Table
from ..normalise import SearchType


class RegistrationTable(Table):
    async def add(self, nickname: str, account: str, email: str) -> int:

        query = """
            INSERT INTO registration (
                nickname,
                search_nick,
                account,
                search_acc,
                email,
                search_email,
                ts
            )
            VALUES ($1, $2, $3, $4, $5, $6, NOW()::TIMESTAMP)
            RETURNING id
        """
        args = [
            nickname,
            str(self.to_search(nickname, SearchType.NICK)),
            account,
            str(self.to_search(account, SearchType.NICK)),
            email,
            str(self.to_search(email, SearchType.EMAIL)),
        ]

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def verify(self, id: int) -> None:
        query = """
            UPDATE registration
            SET verified_at = NOW()::TIMESTAMP
            WHERE id = $1
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, id)
