import re, traceback
from datetime import datetime, timedelta, timezone
from enum import Enum
from ipaddress import ip_address, IPv4Address, IPv6Address
from ipaddress import ip_network, IPv4Network, IPv6Network

from typing import Deque, List, Optional, Sequence, Set, Tuple, Type, Union

from ircrobots import Server
from irctokens import build

from ircchallenge import Challenge
from ircrobots.matching import ANY, Response, SELF
from ircstates.numerics import RPL_ENDOFRSACHALLENGE2, RPL_RSACHALLENGE2

from aiodns import DNSResolver
from aiodns.error import DNSError
from pycares import (
    ares_query_a_result,
    ares_query_aaaa_result,
    ares_query_mx_result,
    ares_query_txt_result,
)

# not in ircstates.numerics
RPL_STATS = "249"
RPL_ENDOFSTATS = "219"

RE_OPERNAME = re.compile(r"^is opered as (\S+)(?:,|$)")

SECONDS_MINUTES = 60
SECONDS_HOURS = SECONDS_MINUTES * 60
SECONDS_DAYS = SECONDS_HOURS * 24
SECONDS_WEEKS = SECONDS_DAYS * 7


class TimeUnit:
    long: str
    short: str
    seconds: int


class TimeUnitSecond(TimeUnit):
    long = "seconds"
    short = "s"
    seconds = 1


class TimeUnitMinute(TimeUnit):
    long = "minutes"
    short = "m"
    seconds = TimeUnitSecond.seconds * 60


class TimeUnitHour(TimeUnit):
    long = "hours"
    short = "h"
    seconds = TimeUnitMinute.seconds * 60


class TimeUnitDay(TimeUnit):
    long = "days"
    short = "d"
    seconds = TimeUnitHour.seconds * 24


class TimeUnitWeek(TimeUnit):
    long = "weeks"
    short = "w"
    seconds = TimeUnitDay.seconds * 7


TIME_UNITS: Sequence[Type[TimeUnit]] = [
    TimeUnitWeek,
    TimeUnitDay,
    TimeUnitHour,
    TimeUnitMinute,
    TimeUnitSecond,
]


def pretty_delta(delta: timedelta, max_units: int = 2, long: bool = False) -> str:
    denominator = int(delta.total_seconds())

    time_units: List[Tuple[Type[TimeUnit], int]] = []
    for time_unit in TIME_UNITS:
        numerator, denominator = divmod(denominator, time_unit.seconds)
        if numerator == 0:
            continue

        time_units.append((time_unit, numerator))
        if len(time_units) == max_units:
            break

    if not time_units:
        time_units.append((TimeUnitSecond, 0))

    outs: List[str] = []
    for time_unit, count in time_units:
        if long:
            outs.append(f"{count} {time_unit.long}")
        else:
            outs.append(f"{count}{time_unit.short}")

    return (" " if long else "").join(outs)


async def oper_up(server: Server, oper_name: str, oper_file: str, oper_pass: str):

    try:
        challenge = Challenge(keyfile=oper_file, password=oper_pass)
    except Exception:
        traceback.print_exc()
    else:
        await server.send(build("CHALLENGE", [oper_name]))
        challenge_text = Response(RPL_RSACHALLENGE2, [SELF, ANY])
        challenge_stop = Response(RPL_ENDOFRSACHALLENGE2, [SELF])
        #:lithium.libera.chat 740 sandcat :foobarbazmeow
        #:lithium.libera.chat 741 sandcat :End of CHALLENGE

        while True:
            challenge_line = await server.wait_for({challenge_text, challenge_stop})
            if challenge_line.command == RPL_RSACHALLENGE2:
                challenge.push(challenge_line.params[1])
            else:
                retort = challenge.finalise()
                await server.send(build("CHALLENGE", [f"+{retort}"]))
                break


RE_STATSPOPER = re.compile(
    r"^(?P<nick>\S+) \((?P<user>\S+)@(?P<host>\S+)\) \{(?P<oper>\S+)\}$"
)


async def get_statsp(server: Server) -> List[Tuple[str, str]]:
    await server.send(build("STATS", ["p"]))

    statsp_texts: List[str] = []
    while True:
        statsp_line = await server.wait_for(
            {
                Response(RPL_STATS, [SELF, "p", ANY]),
                Response(RPL_ENDOFSTATS, [SELF, "p"]),
            }
        )
        if statsp_line.command == RPL_STATS:
            statsp_texts.append(statsp_line.params[2])
        else:
            break

    opers: List[Tuple[str, str]] = []
    for statsp_text in statsp_texts:
        if (match := RE_STATSPOPER.search(statsp_text)) is not None:
            nick = match.group("nick")
            user = match.group("user")
            host = match.group("host")
            oper = match.group("oper")
            mask = f"{nick}!{user}@{host}"
            opers.append((oper, mask))

    return opers


RPL_STATSKLINE = "216"
RPL_ENDOFSTATS = "219"
ERR_NOPRIVS = "723"
# i call these "gline"s but brolanum calls them "propagated kline"s which i
# think is silly
STATS_GLINE_LINE = Response(RPL_STATSKLINE, [SELF, "g", ANY, "*", ANY, ANY])
STATS_KLINE_LINE = Response(RPL_STATSKLINE, [SELF, "k", ANY, "*", ANY, ANY])
STATS_GLINE_END = Response(RPL_ENDOFSTATS, [SELF, "g"])
STATS_KLINE_END = Response(RPL_ENDOFSTATS, [SELF, "k"])
STATS_NOPRIVS = Response(ERR_NOPRIVS, [SELF, ANY])


async def get_klines(server: Server) -> Optional[Set[str]]:
    await server.send(build("STATS", ["g"]))
    await server.send(build("STATS", ["k"]))
    masks: Set[str] = set()

    wait = 2
    while True:
        stats_line = await server.wait_for(
            {
                STATS_GLINE_LINE,
                STATS_KLINE_LINE,
                STATS_GLINE_END,
                STATS_KLINE_END,
                STATS_NOPRIVS,
            }
        )
        if stats_line.command == ERR_NOPRIVS:
            return None
        elif stats_line.command == RPL_STATSKLINE:
            user = stats_line.params[4]
            host = stats_line.params[2]
            masks.add(f"{user}@{host}")
        elif (wait := wait - 1) == 0:
            break
    return masks


def try_parse_ip(ip: str) -> Optional[Union[IPv4Address, IPv6Address]]:

    try:
        return ip_address(ip)
    except ValueError:
        return None


def try_parse_cidr(cidr: str) -> Optional[Union[IPv4Network, IPv6Network]]:

    try:
        return ip_network(cidr, strict=False)
    except ValueError:
        return None


def forgettz(d):
    if d.tzinfo is not None:
        return d.astimezone(tz=timezone.utc).replace(tzinfo=None)
    else:
        return d


TS_FORMATS = [
    # ISO8601 without timezone
    "%Y-%m-%d %H:%M",
    # strange format ERR_YOUREBANNEDCREEP uses
    "%Y/%m/%d %H.%M",
    # ISO8601 with timezone offset
    "%Y-%m-%d %H:%M%z",
]


def try_parse_ts(ts: str) -> Optional[datetime]:
    for ts_format in TS_FORMATS:
        try:
            return forgettz(datetime.strptime(ts, ts_format))
        except ValueError:
            pass
    else:
        return None


class CompositeStringType(Enum):
    TEXT = 1
    SYMBOL = 2


class CompositeStringPart:
    def __init__(self, text: str, type: CompositeStringType):
        self.text = text
        self.type = type

    def __repr__(self) -> str:
        return f"{self.type.name.title()}({self.text})"


class CompositeStringText(CompositeStringPart):
    def __init__(self, text: str):
        super().__init__(text, CompositeStringType.TEXT)


class CompositeStringSymbol(CompositeStringPart):
    def __init__(self, text: str):
        super().__init__(text, CompositeStringType.SYMBOL)


class CompositeString(Deque[CompositeStringPart]):
    def __str__(self) -> str:
        return "".join(p.text for p in self)


WILDCARDS_GLOB = {"?": "_", "*": "%"}
WILDCARDS_SQL = set("_%")


def find_unescaped(s: str, c: Set[str]) -> List[int]:
    indexes: List[int] = []
    i = 0
    while i < len(s):
        c2 = s[i]
        if c2 == "\\":
            i += 1
        elif c2 in c:
            indexes.append(i)
        i += 1
    return indexes


def lex_glob_pattern(glob: str) -> CompositeString:
    out = CompositeString()
    special = set(find_unescaped(glob, set(WILDCARDS_GLOB.keys())))

    for index, char in enumerate(glob):
        if index in special:
            out.append(CompositeStringSymbol(char))
        else:
            out.append(CompositeStringText(char))

    return out


def glob_to_sql(glob: CompositeString) -> CompositeString:
    out = CompositeString()

    for part in glob:
        if part.type == CompositeStringType.SYMBOL:
            sym = WILDCARDS_GLOB[part.text]
            out.append(CompositeStringSymbol(sym))
        elif part.text in WILDCARDS_SQL:
            out.append(CompositeStringSymbol(f"\\{part.text}"))
        else:
            out.append(part)

    return out


def looks_like_glob(s: str) -> bool:
    return bool(set(s) & set("?*"))


def hash_djb2(s: str):
    hash = 5381
    for i, char in enumerate(s):
        hash ^= ((hash << 5) + (hash >> 2) + ord(char)) & 0xFFFFFFFFFFFFFFFF

    return hash


COLOURS = [
    2,  # blue
    3,  # green
    4,  # red
    5,  # brown
    6,  # purple
    7,  # orange
    8,  # yellow
    9,  # light green
    10,  # cyan
    11,  # light cyan
    12,  # light blue
    13,  # pink
]


def colourise(s: str):
    hash = hash_djb2(s)
    colour = COLOURS[hash % len(COLOURS)]
    return f"\x03{str(colour).zfill(2)}{s}\x03"


async def recursive_mx_resolve(
    email_domain: str,
) -> Sequence[Tuple[Optional[int], str, str]]:

    resolver = DNSResolver()

    to_resolve: List[Tuple[Optional[int], str, str]] = [
        (None, "MX", email_domain),
        (None, "A", email_domain),
        (None, "AAAA", email_domain),
        # SPF record
        (None, "TXT", email_domain),
        # DMARC record
        (None, "TXT", f"_dmarc.{email_domain}"),
    ]
    resolved: List[Tuple[Optional[int], str, str]] = []

    while to_resolve:
        record_parent, record_type, name = to_resolve.pop(0)
        try:
            resolves = await resolver.query(name, record_type)
        except DNSError:
            # log an error?
            continue

        for resolve in resolves:
            record_parent_new = len(resolved)
            record = ""
            if isinstance(resolve, ares_query_a_result) or isinstance(resolve, ares_query_aaaa_result) or isinstance(resolve, ares_query_mx_result):
                record = resolve.host
            elif isinstance(resolve, ares_query_txt_result):
                record = resolve.text
            else:
                continue

            resolved.append((record_parent, record_type, record))

            if not record_type == "MX":
                # MX is expected to resolve to a domain that will want to also
                # be resolved
                continue

            to_resolve.append((record_parent_new, "A", resolve.host))
            to_resolve.append((record_parent_new, "AAAA", resolve.host))

    return resolved
