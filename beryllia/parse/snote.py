from datetime import datetime
from ipaddress import ip_address, IPv4Address, IPv6Address
from re import compile as re_compile, X as re_X
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Match,
    Optional,
    Pattern,
    Tuple,
    Union,
)

from irctokens import Line

from .common import IRCParser, RE_EMBEDDEDTAG
from ..database import Database
from ..database.cliconn import Cliconn

_TYPE_HANDLER = Callable[[Any, str, Match], Awaitable[None]]
_HANDLERS: List[Tuple[Pattern, _TYPE_HANDLER]] = []


def _handler(pattern: str) -> Callable[[_TYPE_HANDLER], _TYPE_HANDLER]:
    def _inner(func: _TYPE_HANDLER) -> _TYPE_HANDLER:
        _HANDLERS.append((re_compile(pattern, re_X), func))
        return func

    return _inner


class SnoteParser(IRCParser):
    def __init__(
        self,
        database: Database,
        kline_reject_max: int,
        kline_new: Callable[[int], Awaitable[None]],
    ):
        super().__init__()

        self._database = database
        self._kline_reject_max = kline_reject_max
        self._kline_new = kline_new

        self._cliconns: Dict[str, Tuple[int, Cliconn]] = {}
        self._kline_waiting_exit: Dict[str, str] = {}

    async def handle(self, line: Line) -> None:
        message = line.params[1]

        for pattern, func in _HANDLERS:
            match = pattern.search(message)
            if match is None:
                continue

            await func(self, line.hostmask.nickname, match)
            break

    @_handler(
        r"""
        ^
        # "*** Notice -- Client connecting:"
        \*{3}\ Notice\ --\ Client\ connecting:
        # " nickname"
        \ (?P<nick>\S+)
        # " (user@host)"
        \ \((?P<user>[^@]+)@(?P<host>\S+)\)
        # " [1.2.3.4]"
        \ \[(?P<ip>\S+)\]\ \S+
        # " <account>"
        \ <(?P<account>\S+)>
        # " [real name]"
        \ \[(?P<real>.*)\]
        $
    """
    )
    async def _handle_cliconn(self, server: str, match: Match) -> None:
        nickname = match.group("nick")
        username = match.group("user")
        realname = match.group("real")
        hostname = match.group("host")

        ip: Optional[Union[IPv4Address, IPv6Address]] = None
        if not (ip_str := match.group("ip")) == "0":
            ip = ip_address(ip_str)

        account: Optional[str] = None
        if not (account_ := match.group("account")) == "*":
            account = account_

        cliconn = Cliconn(
            nickname,
            username,
            realname,
            hostname,
            account,
            ip,
            server,
            datetime.utcnow(),
        )
        cliconn_id = await self._database.cliconn.add(cliconn)
        self._cliconns[nickname] = (cliconn_id, cliconn)

    @_handler(
        r"""
        ^
        # "*** Notice -- Client exiting:"
        \*{3}\ Notice\ --\ Client\ exiting:
        # " nickname"
        \ (?P<nick>\S+)
        # " (user@host)"
        \ \((?P<user>[^@]+)@(?P<host>\S+)\)
        # " [quit reason]"
        \ \[(?P<reason>.*)\]
        # " [1.2.3.4]"
        \ \[(?P<ip>\S+)\]
        $
    """
    )
    async def _handle_cliexit(self, server: str, match: Match) -> None:
        nickname = match.group("nick")
        username = match.group("user")
        hostname = match.group("host")
        reason = match.group("reason")

        ip: Optional[Union[IPv4Address, IPv6Address]] = None
        if not (ip_str := match.group("ip")) == "0":
            ip = ip_address(ip_str)

        cliconn_id: Optional[int] = None
        if nickname in self._cliconns:
            cliconn_id, _ = self._cliconns.pop(nickname)

        await self._database.cliexit.add(
            cliconn_id, nickname, username, hostname, ip, reason, server
        )

        if not nickname in self._kline_waiting_exit:
            return

        mask = self._kline_waiting_exit.pop(nickname)
        kline_id = await self._database.kline.find_active(mask)
        if kline_id is None:
            return

        await self._database.kline_kill.add(kline_id, nickname, username, hostname, ip)

    @_handler(
        r"""
        ^
        # "*** Notice -- Rejecting K-Lined user
        \*{3}\ Notice\ --\ Rejecting\ K-Lined\ user
        # " nick[user@host]"
        \ (?P<nick>\S+)\[(?P<user>[^]@]+)@(?P<host>[^]]+)\]
        # " [1.2.3.4]"
        \ \[(?P<ip>\S+)\]
        # " (*@1.2.3.4)"
        \ \((?P<mask>\S+)\)
        $
    """
    )
    async def _handle_klinerej(self, server: str, match: Match) -> None:
        nickname = match.group("nick")
        username = match.group("user")
        hostname = match.group("host")
        mask = match.group("mask")

        ip: Optional[Union[IPv4Address, IPv6Address]] = None
        if not (ip_str := match.group("ip")) == "0":
            ip = ip_address(ip_str)

        kline_id = await self._database.kline.find_active(mask)
        if kline_id is None:
            return

        await self._database.kline.reject_hit(kline_id)

        found = await self._database.kline_reject.find(
            kline_id, nickname, username, hostname
        )
        if found is not None:
            return

        others = await self._database.kline_reject.find_by_hostname(kline_id, hostname)
        if len(others) >= self._kline_reject_max:
            return

        await self._database.kline_reject.add(
            kline_id, nickname, username, hostname, ip
        )

    @_handler(
        r"""
        ^
        # "*** Notice -- Nick change:"
        \*{3}\ Notice\ --\ Nick\ change:
        # " From oldnick"
        \ From\ (?P<old_nick>\S+)
        # " to newnick"
        \ to\ (?P<new_nick>\S+)
        # " [user@host]"
        \ \[\S+\]
        $
    """
    )
    async def _handle_nickchg(self, server: str, match: Match) -> None:
        old_nick = match.group("old_nick")
        if not old_nick in self._cliconns:
            return

        new_nick = match.group("new_nick")
        cliconn_id, cliconn = self._cliconns.pop(old_nick)
        self._cliconns[new_nick] = (cliconn_id, cliconn)
        await self._database.nick_change.add(cliconn_id, new_nick)

    @_handler(
        r"""
        ^
        # "*** Notice -- Disconnecting K-Lined user
        \*{3}\ Notice\ --\ Disconnecting\ K-Lined\ user
        # " nick[user@host]"
        \ (?P<nickname>\S+)\[[^]]+\]
        # " (*@1.2.3.4)"
        \ \((?P<mask>\S+)\)
        $
    """
    )
    async def _handle_klineexit(self, server: str, match: Match) -> None:
        nickname = match.group("nickname")
        mask = match.group("mask")
        # we wait until cliexit because that snote has an IP in it
        self._kline_waiting_exit[nickname] = mask

    @_handler(
        r"""
        ^
        # "*** Notice --"
        \*{3}\ Notice\ --
        # " jess!meow@libera/staff/cat/jess{jess}
        \ (?P<source>[^{]+)\{(?P<oper>[^}]+)\}
        # " added temporary"
        \ added\ (?:temporary|global)
        # " 5 min. K-Line for"
        \ (?P<duration>\d+)\ min\.\ K-Line\ for
        # " [*@1.2.3.4]"
        \ \[(?P<mask>\S+)\]
        # " [k-line reason]"
        \ \[(?P<reason>.*)\]
        $
    """
    )
    async def _handle_klineadd(self, server: str, match: Match) -> None:
        source = match.group("source")
        oper = match.group("oper")
        mask = match.group("mask")
        duration = match.group("duration")
        reason = match.group("reason")

        old_id = await self._database.kline.find_active(mask)
        kline_id = await self._database.kline.add(
            source, oper, mask, int(duration) * 60, reason
        )

        # TODO: just pass a KLine object to _kline_new
        await self._kline_new(kline_id)

        tags = list(RE_EMBEDDEDTAG.finditer(reason))
        for tag_match in tags:
            tag = tag_match.group(1)
            if await self._database.kline_tag.exists(kline_id, tag):
                continue

            await self._database.kline_tag.add(kline_id, tag, source, oper)

        # if an existing k-line is being extended/updated by an oper, update
        # kills affected by the first k-line
        if old_id is None:
            return

        kills = await self._database.kline_kill.find_by_kline(old_id)
        for kill in kills:
            await self._database.kline_kill.set_kline(kill.id, kline_id)

    @_handler(
        r"""
        ^
        # "*** Notice --"
        \*{3}\ Notice\ --
        # " jess!meow@libera/staff/cat/jess{jess}"
        \ (?P<source>[^{]+)\{(?P<oper>[^}]+)\}
        # " has removed the temporary K-Line for:"
        \ has\ removed\ the\ (?:temporary|global)\ K-Line\ for:
        # " [*@1.2.3.4]"
        \ \[(?P<mask>\S+)\]
        $
    """
    )
    async def _handle_klinedel(self, server: str, match: Match) -> None:
        source = match.group("source")
        oper = match.group("oper")
        mask = match.group("mask")

        id = await self._database.kline.find_active(mask)
        if id is None:
            return

        await self._database.kline_remove.add(id, source, oper)
