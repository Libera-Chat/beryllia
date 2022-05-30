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

    async def verify(self, id: int) -> None:
        query = """
            UPDATE registration
            SET verified_at = NOW()::TIMESTAMP
            WHERE id = $1
        """

        async with self.pool.acquire() as conn:
            await conn.execute(query, id)
