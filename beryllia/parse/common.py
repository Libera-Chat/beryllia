from re import compile as re_compile
from irctokens import Line

RE_EMBEDDEDTAG = re_compile(r"%(\S+)")


class IRCParser:
    async def handle(self, line: Line) -> None:
        pass
