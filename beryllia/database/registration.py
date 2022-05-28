from .common import Table

class RegistrationTable(Table):
    async def add(self,
            nickname: str,
            account:  str,
            email:    str) -> int:

        query = """
            INSERT INTO registration (nickname, account, email, ts)
            VALUES ($1, $2, $3, NOW()::TIMESTAMP)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, nickname, account, email)
