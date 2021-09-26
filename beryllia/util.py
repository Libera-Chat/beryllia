import re, traceback
from datetime  import timedelta
from ipaddress import ip_address, IPv4Address, IPv6Address
from ipaddress import ip_network, IPv4Network, IPv6Network

from typing    import List, Optional, Tuple, Union

from ircrobots import Server
from irctokens import build

from ircchallenge       import Challenge
from ircrobots.matching import ANY, Folded, Response, SELF
from ircstates.numerics import *

# not in ircstates.numerics
RPL_STATS      = "249"
RPL_ENDOFSTATS = "219"

RE_OPERNAME = re.compile(r"^is opered as (\S+)(?:,|$)")

SECONDS_MINUTES = 60
SECONDS_HOURS   = SECONDS_MINUTES*60
SECONDS_DAYS    = SECONDS_HOURS*24
SECONDS_WEEKS   = SECONDS_DAYS*7

TIME_UNITS_SHORT = list(zip(
    "wdhms",
    [SECONDS_WEEKS, SECONDS_DAYS, SECONDS_HOURS, SECONDS_MINUTES, 1]
))
TIME_UNITS_LONG  = list(zip(
    ["weeks", "days", "hours", "minutes", "seconds"],
    [SECONDS_WEEKS, SECONDS_DAYS, SECONDS_HOURS, SECONDS_MINUTES, 1]
))

def pretty_delta(
        delta:     timedelta,
        max_units: int=2,
        long:      bool=False
        ) -> str:

    denominator = int(delta.total_seconds())
    outs: List[str] = []
    time_units  = TIME_UNITS_LONG if long else TIME_UNITS_SHORT
    for unit, div in time_units:
        numerator, denominator = divmod(denominator, div)
        if numerator > 0:
            sep = " " if long else ""
            outs.append(f"{numerator}{sep}{unit}")
            if len(outs) == max_units:
                break

    return (" " if long else "").join(outs)

async def oper_up(
        server:    Server,
        oper_name: str,
        oper_file: str,
        oper_pass: str):

    try:
        challenge = Challenge(keyfile=oper_file, password=oper_pass)
    except Exception:
        traceback.print_exc()
    else:
        await server.send(build("CHALLENGE", [oper_name]))
        challenge_text = Response(RPL_RSACHALLENGE2,      [SELF, ANY])
        challenge_stop = Response(RPL_ENDOFRSACHALLENGE2, [SELF])
        #:lithium.libera.chat 740 sandcat :foobarbazmeow
        #:lithium.libera.chat 741 sandcat :End of CHALLENGE

        while True:
            challenge_line = await server.wait_for({
                challenge_text, challenge_stop
            })
            if challenge_line.command == RPL_RSACHALLENGE2:
                challenge.push(challenge_line.params[1])
            else:
                retort = challenge.finalise()
                await server.send(build("CHALLENGE", [f"+{retort}"]))
                break

async def get_whois(
        server:   Server,
        nickname: str
        ) -> Optional[Tuple[str, Optional[str]]]:

    await server.send(build("WHOIS", [nickname]))

    whois_mask = Response(RPL_WHOISUSER,     [SELF, Folded(nickname)])
    whois_oper = Response(RPL_WHOISOPERATOR, [SELF, Folded(nickname)])
    whois_end  = Response(RPL_ENDOFWHOIS,    [SELF, Folded(nickname)])

    whois_line = await server.wait_for({whois_mask, whois_end})
    if whois_line.command == RPL_WHOISUSER:
        nick, user, host = whois_line.params[1:4]
        mask = f"{nick}!{user}@{host}"

        whois_line = await server.wait_for({whois_oper, whois_end})
        if whois_line.command == RPL_WHOISOPERATOR:
            match = RE_OPERNAME.search(whois_line.params[2])
            if match is not None:
                return (mask, match.group(1))
        return (mask, None)
    else:
        return None

async def get_statsp(server: Server) -> List[Tuple[str, str]]:
    await server.send(build("STATS", ["p"]))

    statsp_texts: List[str] = []
    while True:
        statsp_line = await server.wait_for({
            Response(RPL_STATS,      [SELF, "p", ANY]),
            Response(RPL_ENDOFSTATS, [SELF, "p"])
        })
        if statsp_line.command == RPL_STATS:
            statsp_texts.append(statsp_line.params[2])
        else:
            break

    opers: List[Tuple[str, str]] = []
    for statsp_text in statsp_texts[:-1]:
        nick, *_ = statsp_text.split(" ", 1)
        whois    = await get_whois(server, nick)
        if whois is not None:
            mask, oper = whois
            if oper is not None:
                opers.append((oper, mask))

    return opers

def try_parse_ip(
        ip: str
        ) -> Optional[Union[IPv4Address, IPv6Address]]:

    try:
        return ip_address(ip)
    except ValueError:
        return None

def try_parse_cidr(
        cidr: str
        ) -> Optional[Union[IPv4Network, IPv6Network]]:

    try:
        return ip_network(cidr, strict=False)
    except ValueError:
        return None

def glob_to_sql(glob: str) -> str:
    return (glob
        .replace("*", "%")
        .replace("?", "_")
    )
