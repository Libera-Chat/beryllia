from re import compile as re_compile, search as re_search
from typing import Any, Awaitable, Callable, Dict, List, Optional

from irctokens import Line

from .common import IRCParser
from ..database import Database
from ..util import recursive_mx_resolve

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


class NickServParser(IRCParser):
    def __init__(self, database: Database):
        super().__init__()
        self._database = database
        self._registration_ids: Dict[str, int] = {}

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

    async def _resolve_email(self, registration_id: int, email: str) -> None:
        email_parts = email.split("@", 1)
        if not len(email_parts) == 2:
            # log a warning?
            return

        _, email_domain = email_parts
        resolved = await recursive_mx_resolve(email_domain)

        resolved_ids: List[int] = []
        for record_parent, record_type, record in resolved:
            if record_parent is not None:
                record_parent = resolved_ids[record_parent]

            record_id = await self._database.email_resolve.add(
                registration_id, record_parent, record_type, record
            )
            resolved_ids.append(record_id)

    @_handler("REGISTER")
    async def _handle_REGISTER(
        self, nickname: str, _account: Optional[str], args: str
    ) -> None:

        match = re_search("^(?P<account>\S+) to (?P<email>\S+)$", args)
        if match is None:
            return

        account = match.group("account")
        email = match.group("email")

        registration_id = await self._database.registration.add(
            nickname, account, email
        )
        self._registration_ids[account] = registration_id

        await self._resolve_email(registration_id, email)

    @_handler("DROP")
    async def _handle_DROP(
        self, nickname: str, account: Optional[str], args: str
    ) -> None:

        if not args in self._registration_ids:
            return

        del self._registration_ids[args]

    @_handler("SET:ACCOUNTNAME")
    async def _handle_SET_ACCOUNTNAME(
        self, nickname: str, account: Optional[str], args: str
    ) -> None:

        if not account in self._registration_ids:
            return

        registration_id = self._registration_ids.pop(account)
        self._registration_ids[args] = registration_id

    @_handler("VERIFY:REGISTER")
    async def _handle_VERIFY_REGISTER(
        self, nickname: str, _account: Optional[str], args: str
    ) -> None:

        match = re_search(r"^(?P<account>\S+) ", args)
        if match is None:
            return

        account = match.group("account")
        if not account in self._registration_ids:
            return

        registration_id = self._registration_ids[account]
        await self._database.registration.verify(registration_id)
