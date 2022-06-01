from dataclasses import dataclass
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from ipaddress import IPv4Network, IPv6Network
from typing import Any, Optional, Sequence, Tuple, Union

from .common import NickUserHost, Table
from ..normalise import SearchType
from ..util import glob_to_sql, lex_glob_pattern


@dataclass
class DBCliconn(NickUserHost):
    nickname: str
    username: str
    realname: str
    hostname: str
    ip: Union[IPv4Address, IPv6Address]
    server: str
    ts: datetime

    def nuh(self) -> str:
        return f"{self.nickname}!{self.username}@{self.hostname}"


class CliconnTable(Table):
    async def get(self, id: int) -> DBCliconn:
        query = """
            SELECT nickname, username, realname, hostname, ip, server, ts
            FROM cliconn
            WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, id)

        return DBCliconn(*row)

    async def add(
        self,
        nickname: str,
        username: str,
        realname: str,
        hostname: str,
        account: Optional[str],
        ip: Optional[Union[IPv4Address, IPv6Address]],
        server: str,
    ) -> int:

        search_acc: Optional[str] = None
        if account is not None:
            search_acc = str(self.to_search(account, SearchType.NICK))

        query = """
            INSERT INTO cliconn (
                nickname,
                search_nick,
                username,
                search_user,
                realname,
                search_real,
                hostname,
                search_host,
                account,
                search_acc,
                ip,
                server,
                ts
            )
            VALUES (
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                $7,
                $8,
                $9,
                $10,
                $11,
                $12,
                NOW()::TIMESTAMP
            )
            RETURNING id
        """
        args = [
            nickname,
            str(self.to_search(nickname, SearchType.NICK)),
            username,
            str(self.to_search(username, SearchType.USER)),
            realname,
            str(self.to_search(realname, SearchType.REAL)),
            hostname,
            str(self.to_search(hostname, SearchType.HOST)),
            account,
            search_acc,
            ip,
            server,
        ]

        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def _find_cliconns(
        self, where: str, *args: Any
    ) -> Sequence[Tuple[int, datetime]]:

        query = f"""
            SELECT id, ts
            FROM cliconn
            {where}
            ORDER BY ts DESC
            LIMIT 3
        """

        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def find_by_nick(self, nickname: str) -> Sequence[Tuple[int, datetime]]:

        pattern = glob_to_sql(lex_glob_pattern(nickname))
        param = str(self.to_search(pattern, SearchType.NICK))
        return await self._find_cliconns("WHERE search_nick LIKE $1", param)

    async def find_by_user(self, username: str) -> Sequence[Tuple[int, datetime]]:

        pattern = glob_to_sql(lex_glob_pattern(username))
        param = str(self.to_search(pattern, SearchType.USER))
        return await self._find_cliconns("WHERE search_user LIKE $1", param)

    async def find_by_host(self, hostname: str) -> Sequence[Tuple[int, datetime]]:

        pattern = glob_to_sql(lex_glob_pattern(hostname))
        param = str(self.to_search(pattern, SearchType.HOST))
        return await self._find_cliconns("WHERE search_host LIKE $1", param)

    async def find_by_ip(
        self, ip: Union[IPv4Address, IPv6Address]
    ) -> Sequence[Tuple[int, datetime]]:

        return await self._find_cliconns("WHERE ip = $1", ip)

    async def find_by_cidr(
        self, cidr: Union[IPv4Network, IPv6Network]
    ) -> Sequence[Tuple[int, datetime]]:

        return await self._find_cliconns("WHERE ip << $1", cidr)

    async def find_by_ip_glob(self, glob: str) -> Sequence[Tuple[int, datetime]]:

        pattern = glob_to_sql(lex_glob_pattern(glob))
        param = str(self.to_search(pattern, SearchType.HOST))
        return await self._find_cliconns("WHERE TEXT(ip) LIKE $1", param)


class CliexitTable(Table):
    async def add(
        self,
        cliconn: Optional[int],
        nickname: str,
        username: str,
        hostname: str,
        ip: Optional[Union[IPv4Address, IPv6Address]],
        reason: str,
    ) -> int:

        query = """
            INSERT INTO cliexit (
                cliconn_id,
                nickname,
                search_nick,
                username,
                search_user,
                hostname,
                search_host,
                ip,
                reason,
                ts
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW()::TIMESTAMP)
            RETURNING id
        """
        args = [
            cliconn,
            nickname,
            str(self.to_search(nickname, SearchType.NICK)),
            username,
            str(self.to_search(username, SearchType.USER)),
            hostname,
            str(self.to_search(hostname, SearchType.HOST)),
            ip,
            reason,
        ]
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)
