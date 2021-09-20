from dataclasses import dataclass
from datetime    import datetime
from ipaddress   import IPv4Address, IPv6Address
from ipaddress   import IPv4Network, IPv6Network
from typing      import List, Optional, Union

from .common     import Table
from ..normalise import SearchType

@dataclass
class DBCliconn(object):
    nickname: str
    username: str
    realname: str
    hostname: str
    ip:       Union[IPv4Address, IPv6Address]
    ts:       datetime

class CliconnTable(Table):
    async def get(self, id: int) -> Optional[DBCliconn]:
        row = await self.connection.fetchrow("""
            SELECT nickname, username, realname, hostname, ip, ts
            FROM cliconn
            WHERE id = $1
        """, id)
        if row is not None:
            return DBCliconn(*row)
        else:
            return None

    async def add(self,
            nickname: str,
            username: str,
            realname: str,
            hostname: str,
            ip:       Union[IPv4Address, IPv6Address]
            ):

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
                ip,
                ts
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """
        await self.connection.execute(
            query,
            nickname,
            self.to_search(nickname, SearchType.NICK),
            username,
            self.to_search(username, SearchType.USER),
            realname,
            self.to_search(realname, SearchType.REAL),
            hostname,
            self.to_search(hostname, SearchType.HOST),
            ip,
            datetime.utcnow()
        )

    async def find_by_ip(self,
            ip: Union[IPv4Address, IPv6Address]
            ) -> List[int]:

        rows = await self.connection.fetch("""
            SELECT id
            FROM cliconn
            WHERE ip = $1
            ORDER BY ts DESC
        """, ip)
        return [row[0] for row in rows]

    async def find_by_cidr(self,
            cidr: Union[IPv4Network, IPv6Network]
            ) -> List[int]:

        rows = await self.connection.fetch("""
            SELECT id
            FROM cliconn
            WHERE ip << $1
            ORDER BY ts DESC
        """, cidr)
        return [row[0] for row in rows]

    async def find_by_ip_glob(self, glob: str) -> List[int]:
        rows = await self.connection.fetch("""
            SELECT id
            FROM cliconn
            WHERE TEXT(ip) LIKE $1
            ORDER BY ts DESC
        """, glob.replace("*", "%").replace("?", "_"))
        return [row[0] for row in rows]
