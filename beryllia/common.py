from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import Optional, Union


class NickUserHost:
    # nick user host
    def nuh(self) -> str:
        raise NotImplementedError()


@dataclass
class User(NickUserHost):
    nickname: str
    username: str
    realname: str
    hostname: str
    account: Optional[str]
    ip: Optional[Union[IPv4Address, IPv6Address]]
    server: str

    def nuh(self) -> str:
        return f"{self.nickname}!{self.username}@{self.hostname}"
