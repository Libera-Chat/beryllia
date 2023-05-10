import asyncpg
from typing import Any, Optional, Sequence, Tuple

from .cliconn import CliconnTable, CliexitTable
from .nick_change import NickChangeTable
from .statsp import StatsPTable
from .kline import KLineTable
from .kline_kill import KLineKillTable
from .kline_reject import KLineRejectTable
from .kline_remove import KLineRemoveTable
from .kline_tag import KLineTagTable
from .preference import PreferenceTable

from .registration import RegistrationTable
from .email_resolve import EmailResolveTable
from .account_freeze import AccountFreezeTable
from .freeze_tag import FreezeTagTable
from .channel_close import ChannelCloseTable
from .close_tag import CloseTagTable
from .klinechan import KLineChanTable
from .klinechan_tag import KLineChanTagTable

from ..normalise import SearchNormaliser


class DatabaseError(Exception):
    pass


class Database(object):
    def __init__(self, pool: asyncpg.Pool, normaliser: SearchNormaliser):
        self._pool = pool

        self.kline = KLineTable(pool, normaliser)
        self.kline_reject = KLineRejectTable(pool, normaliser)
        self.kline_remove = KLineRemoveTable(pool, normaliser)
        self.kline_kill = KLineKillTable(pool, normaliser)
        self.kline_tag = KLineTagTable(pool, normaliser)
        self.cliconn = CliconnTable(pool, normaliser)
        self.cliexit = CliexitTable(pool, normaliser)
        self.nick_change = NickChangeTable(pool, normaliser)
        self.statsp = StatsPTable(pool, normaliser)
        self.preference = PreferenceTable(pool, normaliser)
        self.registration = RegistrationTable(pool, normaliser)
        self.email_resolve = EmailResolveTable(pool, normaliser)
        self.account_freeze = AccountFreezeTable(pool, normaliser)
        self.freeze_tag = FreezeTagTable(pool, normaliser)
        self.channel_close = ChannelCloseTable(pool, normaliser)
        self.close_tag = CloseTagTable(pool, normaliser)
        self.klinechan = KLineChanTable(pool, normaliser)
        self.klinechan_tag = KLineChanTagTable(pool, normaliser)

    @staticmethod
    async def connect(
        username: str,
        password: Optional[str],
        hostname: Optional[str],
        db_name: str,
        normaliser: SearchNormaliser,
    ):

        pool = await asyncpg.create_pool(
            user=username, password=password, host=hostname, database=db_name
        )
        return Database(pool, normaliser)

    async def readonly_eval(self, query: str) -> Sequence[Tuple[Any, ...]]:
        async with self._pool.acquire() as conn, conn.transaction(readonly=True):
            try:
                rows = await conn.fetch(query)
            except asyncpg.PostgresError as e:
                raise DatabaseError(str(e))

        if not rows:
            return []

        headers = tuple(key for key in rows[0].keys())
        outs = [headers]

        for row in rows:
            outs.append(tuple(value for value in row.values()))

        return outs
