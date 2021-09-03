import asyncio, ipaddress, re, time
from collections import deque, OrderedDict
from dataclasses import dataclass
from datetime    import datetime
from typing      import Deque, Dict, List, Optional, Set, Tuple
from typing      import OrderedDict as TOrderedDict

from irctokens import build, Line
from ircrobots import Bot as BaseBot
from ircrobots import Server as BaseServer
from ircrobots import ConnectionParams

from ircstates.numerics import *
from ircchallenge       import Challenge
from ircrobots.matching import ANY, Folded, Response, SELF

from .config   import Config
from .database import Database

# not in ircstates yet...
RPL_RSACHALLENGE2      = "740"
RPL_ENDOFRSACHALLENGE2 = "741"
RPL_YOUREOPER          = "381"

RE_CLIEXIT   = re.compile(r"^\*{3} Notice -- Client exiting: (?P<nickname>\S+) \((?P<userhost>\S+)\) .* \[(?P<ip>\S+)\]$")
RE_KLINEADD  = re.compile(r"^\*{3} Notice -- (?P<setter>[^{]+)\{\S+ added (?:temporary|global) (?P<duration>\d+) min\. K-Line for \[(?P<mask>\S+)\] \[(?P<reason>.*)\]$")
RE_KLINEDEL  = re.compile(r"^\*{3} Notice -- (?P<remover>[^{]+)\{\S+ has removed the (?:temporary|global) K-Line for: \[(?P<mask>\S+)\]$")
RE_KLINEEXIT = re.compile(r"^\*{3} Notice -- KLINE active for (?P<nickname>[^[]+)\[\S+ .(?P<mask>\S+).$")

SECONDS_MINUTES = 60
SECONDS_HOURS   = SECONDS_MINUTES*60
SECONDS_DAYS    = SECONDS_HOURS*24
SECONDS_WEEKS   = SECONDS_DAYS*7


def _pretty_time(total_seconds: int):
    weeks, days      = divmod(total_seconds, SECONDS_WEEKS)
    days, hours      = divmod(days,          SECONDS_DAYS)
    hours, minutes   = divmod(hours,         SECONDS_HOURS)
    minutes, seconds = divmod(minutes,       SECONDS_MINUTES)

    out = ""
    if not weeks == 0:
        out += f"{weeks}w"
    if not days == 0:
        out += f"{days}d"
    if not hours == 0:
        out += f"{hours}h"
    if not minutes == 0:
        out += f"{minutes}m"
    if not seconds == 0:
        out += f"{seconds}s"
    return out

class Server(BaseServer):
    def __init__(self,
            bot:    BaseBot,
            name:   str,
            config: Config):

        super().__init__(bot, name)
        self._config  = config
        self.database = Database(config.database)

        self._recent_klines: TOrderedDict[str, int] = OrderedDict()
        self._wait_for_exit: Dict[str, str] = {}

    def set_throttle(self, rate: int, time: float):
        # turn off throttling
        pass

    async def _oper_up(self,
            oper_name: str,
            oper_file: str,
            oper_pass: str):

        try:
            challenge = Challenge(keyfile=oper_file, password=oper_pass)
        except Exception:
            traceback.print_exc()
        else:
            await self.send(build("CHALLENGE", [oper_name]))
            challenge_text = Response(RPL_RSACHALLENGE2,      [SELF, ANY])
            challenge_stop = Response(RPL_ENDOFRSACHALLENGE2, [SELF])
            #:lithium.libera.chat 740 sandcat :foobarbazmeow
            #:lithium.libera.chat 741 sandcat :End of CHALLENGE

            while True:
                challenge_line = await self.wait_for({
                    challenge_text, challenge_stop
                })
                if challenge_line.command == RPL_RSACHALLENGE2:
                    challenge.push(challenge_line.params[1])
                else:
                    retort = challenge.finalise()
                    await self.send(build("CHALLENGE", [f"+{retort}"]))
                    break

    async def _is_oper(self, nickname: str):
        await self.send(build("WHOIS", [nickname]))

        whois_oper = Response(RPL_WHOISOPERATOR, [SELF, Folded(nickname)])
        whois_end  = Response(RPL_ENDOFWHOIS,    [SELF, Folded(nickname)])
        #:lithium.libera.chat 313 sandcat sandcat :is an IRC Operator
        #:lithium.libera.chat 318 sandcat sandcat :End of /WHOIS list.

        whois_line = await self.wait_for({
            whois_end, whois_oper
        })
        return whois_line.command == RPL_WHOISOPERATOR

    async def line_read(self, line: Line):
        now = time.monotonic()

        if line.command == RPL_WELCOME:
            await self.send(build("MODE", [self.nickname, "+g"]))
            oper_name, oper_file, oper_pass = self._config.oper
            await self._oper_up(oper_name, oper_file, oper_pass)

        elif line.command == RPL_YOUREOPER:
            # F far cliconn
            # c near cliconn
            # k server kills
            # s oper kills, klines
            await self.send(build("MODE", [self.nickname, "-s+s", "+Fcks"]))

        elif (line.command == "NOTICE" and
                line.params[0] == "*" and
                line.source is not None and
                not "!" in line.source):

            # snote!

            p_cliexit   = RE_CLIEXIT.search(line.params[1])
            p_klineadd  = RE_KLINEADD.search(line.params[1])
            p_klinedel  = RE_KLINEDEL.search(line.params[1])
            p_klineexit = RE_KLINEEXIT.search(line.params[1])

            if p_cliexit is not None:
                nickname = p_cliexit.group("nickname")
                userhost = p_cliexit.group("userhost")
                username, hostname = userhost.split("@")
                ip       = p_cliexit.group("ip")

                if nickname in self._wait_for_exit:
                    mask = self._wait_for_exit.pop(nickname)

                    if mask in self._recent_klines:
                        kline_id = self._recent_klines[mask]
                        await self.database.add_kill(
                            nickname,
                            username,
                            hostname,
                            ip,
                            kline_id
                        )

            if p_klineadd is not None:
                setter   = p_klineadd.group("setter")
                mask     = p_klineadd.group("mask")
                duration = p_klineadd.group("duration")
                reason   = p_klineadd.group("reason")

                username, hostname  = mask.split("@")

                id = await self.database.add_kline(setter, mask, duration, reason)
                self._recent_klines[mask] = id
                self._recent_klines.move_to_end(mask, last=False)
                if len(self._recent_klines) > 64:
                    self._recent_klines.popitem(last=True)

            elif p_klinedel is not None:
                remover = p_klinedel.group("remover")
                mask    = p_klinedel.group("mask")
                id      = await self.database.find_kline(mask)
                if id is not None:
                    await self.database.del_kline(id, remover)

            elif p_klineexit is not None:
                nickname = p_klineexit.group("nickname")
                mask     = p_klineexit.group("mask")
                # we wait until cliexit because that snote has an IP in it
                self._wait_for_exit[nickname] = mask


        elif (line.command == "PRIVMSG" and
                not self.is_me(line.hostmask.nickname)):

            me  = self.nickname
            who = line.hostmask.nickname

            first, _, rest = line.params[1].partition(" ")
            if self.is_me(line.params[0]):
                # private message
                await self.cmd(who, who, first.lower(), rest)
            elif rest:
                if first in [me, f"{me}:", f"{me},"]:
                    # highlight in channel
                    command, _, args = rest.partition(" ")
                    await self.cmd(who, line.params[0], command.lower(), args)

    async def cmd(self,
            who:     str,
            target:  str,
            command: str,
            args:    str):

        if await self._is_oper(who):
            attrib  = f"cmd_{command}"
            if hasattr(self, attrib):
                outs = await getattr(self, attrib)(who, args)
                for out in outs:
                    await self.send(build("NOTICE", [target, out]))

    async def cmd_help(self, nick: str, args: str):
        me      = self.nickname
        command = args.lstrip().split(" ", 1)[0]
        if not command:
            return [
                "available commands: kcheck",
                f"usage: /msg {me} help <command>"
            ]
        elif command == "kcheck":
            return [
                "search for bans that affected a nick/host/ip",
                f"usage: /msg {me} check <nick|host|ip> <query>"
            ]
        else:
            return ["unknown command"]

    async def cmd_kcheck(self, nick: str, args: str):
        type, _, arg = args.partition(" ")
        if arg:
            now  = int(time.time())
            type = type.lower()
            if   type == "nick":
                kills = await self.database.find_kills_by_nick(arg)
            elif type == "host":
                kills = await self.database.find_kills_by_host(arg)
            elif type == "ip":
                kills = await self.database.find_kills_by_ip(arg)
            else:
                return [
                    f"{type} is not a valid type."
                    " valid types are: nick, host, and ip"
                ]

            out: List[str] = []
            for nick, user, host, ts, kline_id in kills[:3]:
                ts_iso = datetime.utcfromtimestamp(ts).isoformat()
                out.append(f"{nick}!{user}@{host} kill at {ts_iso}")

                if kline_id is not None:
                    kline = await self.database.get_kline(kline_id)

                    kts_human   = _pretty_time(now-kline.ts)
                    setter_nick = kline.setter.split("!", 1)[0]
                    kline_s     = (f"K-Line: {kline.mask} {kts_human} ago"
                        f" by {setter_nick} for {kline.duration} mins")

                    if kline.remove_at is not None:
                        remover  = kline.remove_by or "unknown"
                        kline_s += f" (removed by {remover})"
                    elif (kline.ts+(kline.duration*60)) < now:
                        kline_s += " (expired)"

                    kline_s += f": {kline.reason}"
                    out.append(f"  {kline_s}")
            return out or ["no results"]

        else:
            return ["please provide a type and arg"]

    def line_preread(self, line: Line):
        print(f"< {line.format()}")
    def line_presend(self, line: Line):
        print(f"> {line.format()}")

class Bot(BaseBot):
    def __init__(self, config: Config):
        super().__init__()
        self._config = config

    def create_server(self, name: str):
        return Server(self, name, self._config)

