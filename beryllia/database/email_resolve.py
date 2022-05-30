from typing import Optional

from .common import Table

class EmailResolveTable(Table):
    async def add(self,
            registration_id: int,
            record_parent:   Optional[int],
            record_type:     str,
            record:          str) -> int:

        query = """
            INSERT INTO email_resolve
                (registration_id, record_parent, record_type, record)
            VALUES ($1, $2, $3, $4)
            RETURNING id
        """

        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                query, registration_id, record_parent, record_type, record
            )
