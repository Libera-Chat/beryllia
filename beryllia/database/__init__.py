import asyncpg
from typing import Optional

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

from ..normalise import SearchNormaliser


class Database(object):
    def __init__(self, pool: asyncpg.Pool, normaliser: SearchNormaliser):

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
