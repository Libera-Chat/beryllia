from re import compile as re_compile, search as re_search
from typing import Any, Awaitable, Callable, Dict, List, Optional

from irctokens import Line

from .common import IRCParser, RE_EMBEDDEDTAG
from ..database import Database

RE_COMMAND = re_compile(
    r"^(?P<nickname>\S+)"
    # this is optional in command output
    r"( (?P<account>[(]\S*[)]))?"
    r" (?P<command>\S+):"
    r"( (?P<args>.*))?$"
)

_TYPE_HANDLER = Callable[[Any, str, Optional[str], str], Awaitable[None]]
_HANDLERS: Dict[str, _TYPE_HANDLER] = {}


def _handler(command: str) -> Callable[[_TYPE_HANDLER], _TYPE_HANDLER]:
    def _inner(func: _TYPE_HANDLER) -> _TYPE_HANDLER:
        _HANDLERS[command] = func
        return func

    return _inner


class OperServParser(IRCParser):
    def __init__(self, database: Database):
        super().__init__()
        self._database = database

    async def handle(self, line: Line) -> None:
        message = line.params[1]
        match = RE_COMMAND.search(message)
        if match is None:
            return

        command = match.group("command")
        if not command in _HANDLERS:
            return

        nickname = match.group("nickname")
        account = match.group("account")
        args = match.group("args")

        func = _HANDLERS[command]
        await func(self, nickname, account, args)

    @_handler("KLINECHAN:ON")
    async def _handle_KLINECHAN_ON(
        self, soper: str, soper_account: Optional[str], args: str
    ) -> None:

        match = re_search(r"(?P<channel>\S+) \(reason: (?P<reason>.*)\)$", args)
        if match is None:
            return

        soper = soper_account or soper

        channel = match.group("channel")
        reason = match.group("reason")

        close_id = await self._database.klinechan.add(channel, soper, reason)

        tags = list(RE_EMBEDDEDTAG.finditer(reason))
        for tag_match in tags:
            tag = tag_match.group(1)
            if await self._database.klinechan_tag.exists(close_id, tag):
                continue

            await self._database.klinechan_tag.add(close_id, tag, soper)
